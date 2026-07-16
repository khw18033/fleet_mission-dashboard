"""
mission-listener/listener.py — 제어용 RPi (k3s role=robot)

역할:
  1. fleet/mission/broadcast 구독 → 조건 매칭 → accept/reject
  2. accept 후 미션 저장 + Redis LPUSH → link_proxy 실행
  3. 체크포인트 cache 토픽 발행
  4. fleet/handover/{robot_id} 구독 → 미션 중단 없이 새 기지국으로 재연결

핸드오버 흐름:
  handover_controller → MQTT fleet/handover/{sn}
      → listener 수신 → 현재 미션 step_index 보존
      → 새 기지국 broadcaster가 resume_from=step_index로 재브로드캐스트
      → listener accept → 해당 step부터 재개
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
    format="%(asctime)s [%(levelname)s] listener: %(message)s",
)
log = logging.getLogger("listener")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}
        self._hashes = {}
        self._lists = {}

    def ping(self):
        return True

    def exists(self, key):
        return key in self._strings or key in self._hashes or key in self._lists

    def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    def lpush(self, key, value):
        self._lists.setdefault(key, []).insert(0, value)

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def get(self, key):
        return self._strings.get(key)

MQTT_HOST      = os.getenv("MQTT_HOST",      cfg.get("mqtt.host", "localhost"))
MQTT_PORT      = int(os.getenv("MQTT_PORT",  str(cfg.get("mqtt.port", 1883))))
ROBOT_ID       = os.getenv("ROBOT_ID",       cfg.get("runtime.default_robot_sn", "unknown"))
ROBOT_TYPE     = os.getenv("ROBOT_TYPE",     cfg.get("robot.type", "ep01"))
ROBOT_ONLINE   = os.getenv("ROBOT_ONLINE",   "true").lower() == "true"
BATTERY_LEVEL  = int(os.getenv("BATTERY_LEVEL", "100"))
MISSION_STORE  = Path(os.getenv("MISSION_STORE", "/data/missions"))
REDIS_HOST     = os.getenv("REDIS_HOST",     cfg.get("network.redis_host", "redis-service"))
REDIS_PORT_NUM = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))
KEEPALIVE      = int(cfg.get("mqtt.keepalive", 60))

REDIS_CMD_KEY    = f"robot:{ROBOT_ID}:commands"
REDIS_STATUS_KEY = f"robot:{ROBOT_ID}:status"
REDIS_ONLINE_KEY = f"robot:{ROBOT_ID}:online"

TOPIC_BROADCAST = "fleet/mission/broadcast"
TOPIC_HANDOVER  = f"fleet/handover/{ROBOT_ID}"
TOPIC_CACHE_TPL = "fleet/mission/cache/{robot_id}"

try:
    if MOCK_MODE:
        r = MockRedis()
        log.info("Redis mock store enabled")
    else:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT_NUM, db=0, decode_responses=True)
        r.ping()
        log.info(f"Redis connected: {REDIS_HOST}:{REDIS_PORT_NUM}")
except Exception as e:
    log.warning(f"Redis 연결 실패: {e}")
    r = MockRedis() if MOCK_MODE else None

_current_mission: dict | None = None
_mission_lock  = threading.Lock()
_mission_abort = threading.Event()   # 핸드오버 시 현재 미션 중단 신호


def get_robot_status() -> dict:
    """link_proxy의 Redis 상태 우선, 없으면 환경변수 폴백."""
    status = {
        "robot_id":      ROBOT_ID,
        "robot_type":    ROBOT_TYPE,
        "robot_online":  ROBOT_ONLINE,
        "battery_level": BATTERY_LEVEL,
        "latency_ms":    0,
    }
    if r is None:
        return status
    try:
        # heartbeat 키로 온라인 판단 (link_proxy가 갱신)
        online = bool(r.exists(REDIS_ONLINE_KEY))
        status["robot_online"] = online

        raw = r.hgetall(REDIS_STATUS_KEY)
        if raw:
            batt_raw = raw.get("battery")
            if batt_raw:
                batt = json.loads(batt_raw)
                status["battery_level"] = int(batt.get("soc", BATTERY_LEVEL))
    except Exception as e:
        log.warning(f"Redis 상태 읽기 실패: {e}")
    return status


def evaluate_conditions(conditions: dict, status: dict) -> tuple[bool, str]:
    if not conditions:
        return True, ""
    required_type = conditions.get("robot_type")
    if required_type and status["robot_type"] != required_type:
        return False, f"robot_type mismatch: need={required_type} have={status['robot_type']}"
    if conditions.get("robot_online", True) and not status["robot_online"]:
        return False, "robot is offline"
    min_battery = int(conditions.get("min_battery", 0))
    if status["battery_level"] < min_battery:
        return False, f"battery {status['battery_level']}% < {min_battery}%"
    max_latency = int(conditions.get("max_latency_ms", 9999))
    if status["latency_ms"] > max_latency:
        return False, f"latency {status['latency_ms']}ms > {max_latency}ms"
    return True, ""


def save_mission(payload: dict) -> Path:
    MISSION_STORE.mkdir(parents=True, exist_ok=True)
    mission_id = payload["mission_id"]
    path = MISSION_STORE / f"{mission_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # last-mission.json 도 갱신 (fallback용)
    last_path = MISSION_STORE / "last-mission.json"
    with open(last_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info(f"Mission saved: {path}")
    return path


def execute_mission(client: mqtt.Client, payload: dict, start_from: int = 0):
    """
    start_from: 핸드오버 재개 시 해당 step부터 실행.
    _mission_abort 이벤트가 설정되면 즉시 중단.
    """
    global _current_mission
    _mission_abort.clear()

    nodes      = payload.get("nodes", [])
    mission_id = payload["mission_id"]
    total      = len(nodes)
    cache_topic = TOPIC_CACHE_TPL.format(robot_id=ROBOT_ID)

    log.info(f"Mission start: {mission_id} ({total} nodes, from={start_from})")

    for idx in range(start_from, total):
        # 핸드오버 중단 신호 확인
        if _mission_abort.is_set():
            log.info(f"Mission {mission_id} 핸드오버로 중단 (step={idx})")
            break

        node = nodes[idx]
        with _mission_lock:
            _current_mission = {
                **payload,
                "_step_index":   idx,
                "_progress_pct": int(idx / max(total, 1) * 100),
            }

        cmd = {
            "target": node.get("target"),
            "action": node.get("action"),
            "params": node.get("params", {}),
        }
        if r:
            try:
                r.lpush(REDIS_CMD_KEY, json.dumps(cmd))
                log.info(f"  [{idx+1}/{total}] {cmd['target']}.{cmd['action']}")
            except Exception as e:
                log.error(f"  Redis LPUSH 실패: {e}")

        cache_payload = {
            "mission_id":   mission_id,
            "robot_id":     ROBOT_ID,
            "step_index":   idx,
            "progress_pct": int(idx / max(total, 1) * 100),
            "last_node":    node,
            "timestamp":    time.time(),
        }
        client.publish(cache_topic, json.dumps(cache_payload), qos=1)

        delay = float(node.get("delay_sec", 0) or 0)
        if delay > 0:
            # 핸드오버 중단 신호를 delay 중에도 체크
            _mission_abort.wait(timeout=delay)

    if not _mission_abort.is_set():
        done = {
            "mission_id":   mission_id,
            "robot_id":     ROBOT_ID,
            "step_index":   total,
            "progress_pct": 100,
            "last_node":    nodes[-1] if nodes else {},
            "timestamp":    time.time(),
            "status":       "completed",
        }
        client.publish(cache_topic, json.dumps(done), qos=1)
        log.info(f"Mission {mission_id} completed")

    with _mission_lock:
        _current_mission = None


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info(f"MQTT connected — robot={ROBOT_ID} type={ROBOT_TYPE}")
        client.subscribe(TOPIC_BROADCAST, qos=1)
        client.subscribe(TOPIC_HANDOVER,  qos=1)
        log.info(f"Subscribed: {TOPIC_BROADCAST}, {TOPIC_HANDOVER}")
    else:
        log.error(f"MQTT connect failed rc={rc}")


def on_broadcast(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Broadcast parse error: {e}"); return

    mission_id  = payload.get("mission_id", "unknown")
    station_id  = payload.get("station_id", "unknown")
    conditions  = payload.get("conditions", {})
    resume_from = int(payload.get("resume_from", 0))

    with _mission_lock:
        # 핸드오버 재개가 아닌 신규 미션이고 현재 실행 중이면 무시
        if _current_mission is not None and resume_from == 0:
            log.info(f"Mission {mission_id} ignored — executing {_current_mission.get('mission_id')}")
            return

    status   = get_robot_status()
    accepted, reason = evaluate_conditions(conditions, status)

    accept_topic = f"fleet/mission/accept/{station_id}"
    response = {
        "mission_id": mission_id,
        "robot_id":   ROBOT_ID,
        "robot_type": ROBOT_TYPE,
        "decision":   "accept" if accepted else "reject",
        "reason":     reason,
        "status":     status,
        "timestamp":  time.time(),
    }
    client.publish(accept_topic, json.dumps(response), qos=1)
    log.info(f"{'ACCEPT' if accepted else 'REJECT'} mission={mission_id} reason={reason or 'ok'}")

    if accepted:
        save_mission(payload)
        t = threading.Thread(
            target=execute_mission,
            args=(client, payload, resume_from),
            daemon=True,
            name=f"mission-{mission_id}",
        )
        t.start()


def on_handover(client, userdata, msg):
    """
    핸드오버 컨트롤러 → fleet/handover/{robot_id}
    현재 미션을 중단하고 새 기지국 브로드캐스트를 기다림.
    """
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Handover parse error: {e}"); return

    from_sta = payload.get("from_station")
    to_sta   = payload.get("to_station")
    log.info(f"핸드오버 수신 — {from_sta} → {to_sta}")

    with _mission_lock:
        if _current_mission is not None:
            log.info(f"  현재 미션 중단: {_current_mission.get('mission_id')}")
            _mission_abort.set()


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_BROADCAST:
        on_broadcast(client, userdata, msg)
    elif msg.topic == TOPIC_HANDOVER:
        on_handover(client, userdata, msg)


def main():
    log.info(f"Mission Listener 시작 — robot={ROBOT_ID} type={ROBOT_TYPE}")
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — MQTT loop skipped")
        return
    client = mqtt.Client(client_id=f"listener-{ROBOT_ID}")
    client.on_connect = on_connect
    client.on_message = on_message
    log.info(f"Connecting MQTT {MQTT_HOST}:{MQTT_PORT} ...")
    client.connect(MQTT_HOST, MQTT_PORT, KEEPALIVE)
    client.loop_forever()


if __name__ == "__main__":
    main()
