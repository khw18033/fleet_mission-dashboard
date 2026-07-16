"""
handover_controller.py — 기지국 RPi (edge role) 에서 실행
RSSI 기반 핸드오버 판단 → Prewarm 트리거 → 체크포인트 전달

핸드오버 조건:
  B_ewma - A_ewma > threshold  AND  stable_count번 연속 감지
  AND  마지막 핸드오버로부터 cooldown_sec 이상 경과

흐름:
  1. Redis rssi:{station_id}:{sn} 수집
  2. 가장 강한 기지국(best) 판단
  3. 현재 active 기지국과 다르면 stable counter 증가
  4. stable_count 달성 → Prewarm 발행 → cooldown 대기
  5. MQTT fleet/handover/{sn} 발행 → broadcaster/listener가 체크포인트 이관

환경변수:
  STATION_ID   이 기지국 ID
  REDIS_HOST
  MQTT_HOST, MQTT_PORT
"""
import json, logging, os, sys, time
from pathlib import Path
from threading import Thread

import paho.mqtt.client as mqtt
import redis

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.config_loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] handover_ctrl: %(message)s",
)
log = logging.getLogger("handover-ctrl")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}

    def ping(self):
        return True

    def get(self, key):
        return self._strings.get(key)

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def keys(self, pattern):
        return list(self._strings.keys())

STATION_ID = os.getenv("STATION_ID",  "station-a")
REDIS_HOST = os.getenv("REDIS_HOST",  cfg.get("network.redis_host", "redis-service"))
REDIS_PORT = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))
MQTT_HOST  = os.getenv("MQTT_HOST",   cfg.get("mqtt.host",  "localhost"))
MQTT_PORT  = int(os.getenv("MQTT_PORT", str(cfg.get("mqtt.port", 1883))))

THRESHOLD    = float(cfg.get("services.handover.rssi_threshold_db",  10))
HYSTERESIS   = float(cfg.get("services.handover.hysteresis_db",       3))
COOLDOWN     = float(cfg.get("services.handover.cooldown_sec",        15))
STABLE_COUNT = int(cfg.get("services.handover.stable_count",          3))
SCAN_INTERVAL= float(cfg.get("services.rssi.scan_interval_sec",       3))
SSID_TO_SN   = cfg.get("robot.ap.ssid_to_sn", {}) or {}

# 모든 기지국 목록
ALL_STATIONS = [s["id"] for s in (cfg.get("stations", []) or [])]

try:
    if MOCK_MODE:
        r = MockRedis()
        log.info("Redis mock store enabled")
    else:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
        r.ping()
        log.info(f"Redis connected: {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    log.error(f"Redis 연결 실패: {e}")
    if MOCK_MODE:
        r = MockRedis()
    else:
        sys.exit(1)

_mqtt_client: mqtt.Client | None = None


def setup_mqtt():
    global _mqtt_client
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — MQTT setup skipped")
        _mqtt_client = None
        return
    try:
        _mqtt_client = mqtt.Client(client_id=f"handover-{STATION_ID}")
        _mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        _mqtt_client.loop_start()
        log.info(f"MQTT connected: {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        log.warning(f"MQTT 연결 실패: {e}")
        _mqtt_client = None


def publish(topic: str, payload: dict) -> None:
    if _mqtt_client:
        try:
            _mqtt_client.publish(topic, json.dumps(payload), qos=1)
        except Exception as e:
            log.warning(f"MQTT publish 실패 ({topic}): {e}")


def get_all_rssi(sn: str) -> dict[str, float]:
    """모든 기지국의 Redis에서 해당 로봇의 RSSI 읽기."""
    result: dict[str, float] = {}
    for station in ALL_STATIONS:
        key = f"rssi:{station}:{sn}"
        raw = r.get(key)
        if raw:
            try:
                data = json.loads(raw)
                result[station] = float(data.get("ewma", data.get("rssi", -100)))
            except Exception:
                pass
    return result


def get_checkpoint(sn: str) -> dict | None:
    """현재 미션 체크포인트 조회."""
    raw = r.get(f"fleet:cache:{sn}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return None


def get_all_robot_sns() -> list[str]:
    """Redis에서 활성 로봇 SN 목록 조회."""
    sns = set()
    for key in r.keys("rssi:*:*"):
        parts = key.split(":")
        if len(parts) == 3:
            sns.add(parts[2])
    # ssid_to_sn 테이블에 등록된 SN도 포함
    for sn in SSID_TO_SN.values():
        sns.add(sn)
    return list(sns)


class HandoverState:
    def __init__(self, sn: str):
        self.sn           = sn
        self.active_sta   = STATION_ID   # 현재 active 기지국 (자신으로 초기화)
        self.stable_cnt   = 0
        self.candidate    = None          # 핸드오버 후보 기지국
        self.last_ho_time = 0.0

    def update(self, rssi_map: dict[str, float]) -> None:
        if not rssi_map:
            return

        now = time.time()
        best_sta = max(rssi_map, key=rssi_map.get)
        best_val = rssi_map[best_sta]
        curr_val = rssi_map.get(self.active_sta, -100)

        # 핸드오버 조건: best가 현재보다 threshold 이상 강하고 쿨다운 지남
        if (best_sta != self.active_sta
                and best_val - curr_val > THRESHOLD
                and now - self.last_ho_time > COOLDOWN):

            if self.candidate == best_sta:
                self.stable_cnt += 1
            else:
                self.candidate  = best_sta
                self.stable_cnt = 1

            log.info(
                f"  [{self.sn}] 후보={best_sta}({best_val:.1f}dBm) "
                f"현재={self.active_sta}({curr_val:.1f}dBm) "
                f"stable={self.stable_cnt}/{STABLE_COUNT}"
            )

            if self.stable_cnt >= STABLE_COUNT:
                self._trigger_handover(best_sta, rssi_map)

        else:
            # 히스테리시스: 조건 미달 시 카운터 리셋
            if best_val - curr_val <= THRESHOLD - HYSTERESIS:
                self.stable_cnt = 0
                self.candidate  = None

    def _trigger_handover(self, target_sta: str, rssi_map: dict[str, float]) -> None:
        checkpoint = get_checkpoint(self.sn)
        now = time.time()

        log.info(
            f"핸드오버 트리거: robot={self.sn} "
            f"{self.active_sta} → {target_sta}"
        )

        # ── Redis에 핸드오버 이벤트 기록 ──────────────────────────
        ho_data = {
            "robot_sn":    self.sn,
            "from_station": self.active_sta,
            "to_station":   target_sta,
            "rssi_map":     rssi_map,
            "checkpoint":   checkpoint,
            "ts":           now,
        }
        r.set(f"handover:{self.sn}", json.dumps(ho_data), ex=300)

        # ── Prewarm: 대상 기지국에 준비 신호 ─────────────────────
        publish(
            f"fleet/handover/prewarm/{target_sta}",
            {
                "robot_sn":    self.sn,
                "from_station": self.active_sta,
                "checkpoint":   checkpoint,
                "ts":           now,
            },
        )

        # ── Handover 실행: 제어용 RPi에 통보 ─────────────────────
        publish(
            f"fleet/handover/{self.sn}",
            {
                "robot_sn":    self.sn,
                "from_station": self.active_sta,
                "to_station":   target_sta,
                "checkpoint":   checkpoint,
                "ts":           now,
            },
        )

        self.active_sta   = target_sta
        self.last_ho_time = now
        self.stable_cnt   = 0
        self.candidate    = None


def main():
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — handover loop skipped")
        return
    setup_mqtt()
    log.info(
        f"Handover Controller 시작 — station={STATION_ID} "
        f"threshold={THRESHOLD}dB hysteresis={HYSTERESIS}dB "
        f"cooldown={COOLDOWN}s stable={STABLE_COUNT}"
    )

    states: dict[str, HandoverState] = {}

    while True:
        try:
            sns = get_all_robot_sns()
            for sn in sns:
                if sn not in states:
                    states[sn] = HandoverState(sn)
                rssi_map = get_all_rssi(sn)
                if rssi_map:
                    log.debug(f"[{sn}] RSSI: {rssi_map}")
                    states[sn].update(rssi_map)
        except Exception as e:
            log.error(f"메인 루프 에러: {e}", exc_info=True)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
