"""
fallback_controller.py — 제어용 RPi (k3s role=robot)

중앙 서버(MQTT 브로커) 단절 감지 → last-mission.json 자동 실행
재연결 시 → 서버 미션으로 복귀

단절 감지:
  MQTT 연결 끊김 on_disconnect 콜백
  Redis heartbeat 키 만료 (서버 heartbeat publisher가 갱신하지 않으면 TTL 만료)

환경변수:
  ROBOT_ID
  REDIS_HOST
  MQTT_HOST, MQTT_PORT
  MISSION_STORE
"""
import json, logging, os, sys, time, threading
from pathlib import Path

import paho.mqtt.client as mqtt
import redis

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.config_loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] fallback_ctrl: %(message)s",
)
log = logging.getLogger("fallback-ctrl")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}
        self._lists = {}

    def ping(self):
        return True

    def lpush(self, key, value):
        self._lists.setdefault(key, []).insert(0, value)

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    def exists(self, key):
        return key in self._strings or key in self._lists

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def get(self, key):
        return self._strings.get(key)

ROBOT_ID       = os.getenv("ROBOT_ID",       cfg.get("runtime.default_robot_sn", "unknown"))
REDIS_HOST     = os.getenv("REDIS_HOST",     cfg.get("network.redis_host", "redis-service"))
REDIS_PORT_NUM = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))
MQTT_HOST      = os.getenv("MQTT_HOST",      cfg.get("mqtt.host", "localhost"))
MQTT_PORT      = int(os.getenv("MQTT_PORT",  str(cfg.get("mqtt.port", 1883))))
MISSION_STORE  = Path(os.getenv("MISSION_STORE", "/data/missions"))
KEEPALIVE      = int(cfg.get("mqtt.keepalive", 60))

# 서버 heartbeat 키 (central-hub가 주기적으로 갱신)
SERVER_HB_KEY     = "fleet:server:heartbeat"
SERVER_HB_TIMEOUT = 20   # N초 내에 heartbeat 없으면 단절로 판단
RECONNECT_WAIT    = 10   # 재연결 시도 간격

REDIS_CMD_KEY = f"robot:{ROBOT_ID}:commands"
LAST_MISSION  = MISSION_STORE / "last-mission.json"

try:
    if MOCK_MODE:
        r = MockRedis()
        log.info("Redis mock store enabled")
    else:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT_NUM, db=0, decode_responses=True)
        r.ping()
        log.info(f"Redis connected: {REDIS_HOST}:{REDIS_PORT_NUM}")
except Exception as e:
    log.error(f"Redis 연결 실패: {e}")
    if MOCK_MODE:
        r = MockRedis()
    else:
        sys.exit(1)

_connected     = threading.Event()
_connected.set()   # 초기엔 연결 상태로 가정
_fallback_active = False


def load_last_mission() -> dict | None:
    if LAST_MISSION.exists():
        try:
            with open(LAST_MISSION) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"last-mission.json 읽기 실패: {e}")
    return None


def execute_fallback(mission: dict) -> None:
    """last-mission.json 의 노드를 Redis LPUSH로 실행."""
    global _fallback_active
    _fallback_active = True
    nodes      = mission.get("nodes", [])
    mission_id = mission.get("mission_id", "fallback")
    log.info(f"Fallback 미션 실행: {mission_id} ({len(nodes)} nodes)")

    for idx, node in enumerate(nodes):
        if _connected.is_set():
            log.info("서버 재연결 감지 — Fallback 중단")
            break
        cmd = {
            "id":     f"{mission_id}:{idx}",   # ack 상관관계용 (protocol v1)
            "target": node.get("target"),
            "action": node.get("action"),
            "params": node.get("params", {}),
        }
        try:
            # protocol v1: FIFO 보장을 위해 RPUSH (소비자는 BLPOP)
            r.rpush(REDIS_CMD_KEY, json.dumps(cmd))
            log.info(f"  Fallback [{idx+1}/{len(nodes)}] {cmd['target']}.{cmd['action']}")
        except Exception as e:
            log.error(f"  Fallback LPUSH 실패: {e}")

        delay = float(node.get("delay_sec", 1) or 1)
        time.sleep(delay)

    _fallback_active = False
    log.info("Fallback 미션 완료")


def check_server_heartbeat() -> bool:
    """Redis의 서버 heartbeat 키 존재 여부로 서버 생존 확인."""
    try:
        return bool(r.exists(SERVER_HB_KEY))
    except Exception:
        return False


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("MQTT 서버 연결됨 — 정상 모드")
        _connected.set()
    else:
        log.warning(f"MQTT 연결 실패 rc={rc}")
        _connected.clear()


def on_disconnect(client, userdata, rc):
    log.warning(f"MQTT 서버 단절 (rc={rc})")
    _connected.clear()


def heartbeat_monitor():
    """서버 heartbeat를 주기적으로 확인."""
    global _fallback_active
    while True:
        hb_alive = check_server_heartbeat()
        mqtt_alive = _connected.is_set()

        server_ok = hb_alive and mqtt_alive

        if not server_ok and not _fallback_active:
            log.warning("서버 단절 감지 — Fallback 모드 진입")
            mission = load_last_mission()
            if mission:
                t = threading.Thread(target=execute_fallback, args=(mission,), daemon=True)
                t.start()
            else:
                log.warning("last-mission.json 없음 — 대기")

        elif server_ok and _fallback_active:
            log.info("서버 재연결 — Fallback 모드 종료")
            # execute_fallback이 _connected.is_set() 체크로 자동 중단됨

        time.sleep(SERVER_HB_TIMEOUT // 2)


def main():
    log.info(f"Fallback Controller 시작 — robot={ROBOT_ID}")
    MISSION_STORE.mkdir(parents=True, exist_ok=True)

    if MOCK_MODE:
        log.info("MOCK_MODE=1 — MQTT/heartbeat loop skipped")
        return

    client = mqtt.Client(client_id=f"fallback-{ROBOT_ID}")
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect

    # MQTT 연결 (실패해도 heartbeat monitor는 계속 작동)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, KEEPALIVE)
        client.loop_start()
    except Exception as e:
        log.warning(f"MQTT 초기 연결 실패: {e} — heartbeat 모니터만 실행")
        _connected.clear()

    # heartbeat 모니터 스레드
    threading.Thread(target=heartbeat_monitor, daemon=True).start()

    # 재연결 루프
    while True:
        if not _connected.is_set():
            try:
                client.reconnect()
                log.info("MQTT 재연결 시도...")
            except Exception as e:
                log.debug(f"재연결 실패: {e}")
        time.sleep(RECONNECT_WAIT)


if __name__ == "__main__":
    main()
