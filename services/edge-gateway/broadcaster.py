"""
edge-gateway/broadcaster.py — 기지국 RPi (k3s role=edge)

역할:
  1. fleet/mission/deploy 구독 → 브로드캐스트
  2. accept/reject 수신 → 서버 릴레이
  3. 체크포인트 캐시 보관
  4. fleet/handover/prewarm/{station_id} 수신 → 체크포인트 보존 후 미션 재브로드캐스트 준비 (핸드오버)
"""
import json, logging, os, sys, time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.config_loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] broadcaster: %(message)s",
)
log = logging.getLogger("broadcaster")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"

MQTT_HOST  = os.getenv("MQTT_HOST",  cfg.get("mqtt.host",  "localhost"))
MQTT_PORT  = int(os.getenv("MQTT_PORT", str(cfg.get("mqtt.port", 1883))))
STATION_ID = os.getenv("STATION_ID", "station-a")
KEEPALIVE  = int(cfg.get("mqtt.keepalive", 60))

TOPIC_DEPLOY    = "fleet/mission/deploy"
TOPIC_BROADCAST = "fleet/mission/broadcast"
TOPIC_ACCEPT    = f"fleet/mission/accept/{STATION_ID}"
TOPIC_RELAY     = "fleet/mission/accepted"
TOPIC_CACHE     = "fleet/mission/cache/{robot_id}"
TOPIC_PREWARM   = f"fleet/handover/prewarm/{STATION_ID}"   # 핸드오버 Prewarm 수신

# mission_id → payload (체크포인트 포함)
_active_missions: dict[str, dict] = {}


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info(f"MQTT connected — station={STATION_ID}")
        client.subscribe(TOPIC_DEPLOY,   qos=1)
        client.subscribe(TOPIC_ACCEPT,   qos=1)
        client.subscribe(TOPIC_PREWARM,  qos=1)
        log.info(f"Subscribed: {TOPIC_DEPLOY}, {TOPIC_ACCEPT}, {TOPIC_PREWARM}")
    else:
        log.error(f"MQTT connect failed rc={rc}")


def on_deploy(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Deploy parse error: {e}"); return

    mission_id      = payload.get("mission_id", f"mission-{int(time.time())}")
    target_stations = payload.get("target_stations", [])

    if target_stations and STATION_ID not in target_stations:
        log.info(f"Mission {mission_id} not targeting {STATION_ID}, skipping")
        return

    _active_missions[mission_id] = payload
    _do_broadcast(client, mission_id, payload)


def _do_broadcast(client, mission_id: str, payload: dict,
                  resume_from: int = 0) -> None:
    """브로드캐스트 실행. resume_from > 0 이면 핸드오버 재개."""
    nodes = payload.get("nodes", [])
    if resume_from > 0:
        nodes = nodes[resume_from:]
        log.info(f"핸드오버 재개 — mission={mission_id} step={resume_from}부터")

    bc = {
        "mission_id":   mission_id,
        "station_id":   STATION_ID,
        "mission_name": payload.get("mission_name", ""),
        "conditions":   payload.get("conditions", {}),
        "nodes":        nodes,
        "resume_from":  resume_from,
        "timestamp":    time.time(),
    }
    client.publish(TOPIC_BROADCAST, json.dumps(bc), qos=1)
    log.info(f"Broadcasted mission {mission_id} (resume_from={resume_from})")


def on_accept(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Accept parse error: {e}"); return

    mission_id = payload.get("mission_id")
    robot_id   = payload.get("robot_id")
    decision   = payload.get("decision")
    log.info(f"Accept: {decision} mission={mission_id} robot={robot_id}")

    relay_payload = {**payload, "station_id": STATION_ID, "relayed_at": time.time()}
    client.publish(TOPIC_RELAY, json.dumps(relay_payload), qos=1)

    if decision == "accept" and robot_id:
        cache_topic = TOPIC_CACHE.format(robot_id=robot_id)
        client.subscribe(cache_topic, qos=1)
        log.info(f"Cache 구독: {cache_topic}")


def on_cache(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Cache parse error: {e}"); return

    robot_id   = payload.get("robot_id")
    mission_id = payload.get("mission_id")
    progress   = payload.get("progress_pct", 0)

    if mission_id in _active_missions:
        _active_missions[mission_id]["_checkpoint"] = payload

    log.debug(f"Cache — robot={robot_id} mission={mission_id} {progress}%")


def on_prewarm(client, userdata, msg):
    """
    핸드오버 컨트롤러가 이 기지국을 target으로 선정 → Prewarm 수신
    체크포인트에서 step_index 읽어 미션 재브로드캐스트 준비.
    """
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.warning(f"Prewarm parse error: {e}"); return

    robot_sn     = payload.get("robot_sn")
    from_station = payload.get("from_station")
    checkpoint   = payload.get("checkpoint")

    log.info(f"🔄 Prewarm 수신 — robot={robot_sn} from={from_station}")

    if not checkpoint:
        log.warning("Prewarm: 체크포인트 없음 — 재브로드캐스트 불가")
        return

    mission_id  = checkpoint.get("mission_id")
    step_index  = checkpoint.get("step_index", 0)

    # 이 기지국이 해당 미션을 알고 있는지 확인
    if mission_id not in _active_missions:
        log.warning(f"Prewarm: mission {mission_id} 미보유 — fleet/mission/cache 에서 복원 시도")
        # 체크포인트 payload에서 임시 복원
        _active_missions[mission_id] = checkpoint.get("_full_payload", {})

    original = _active_missions.get(mission_id, {})
    if original:
        _do_broadcast(client, mission_id, original, resume_from=step_index)
    else:
        log.warning(f"Prewarm: mission {mission_id} 복원 실패")


def on_message(client, userdata, msg):
    topic = msg.topic
    if topic == TOPIC_DEPLOY:
        on_deploy(client, userdata, msg)
    elif topic == TOPIC_ACCEPT:
        on_accept(client, userdata, msg)
    elif topic == TOPIC_PREWARM:
        on_prewarm(client, userdata, msg)
    elif topic.startswith("fleet/mission/cache/"):
        on_cache(client, userdata, msg)
    else:
        log.debug(f"Unhandled: {topic}")


def main():
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — broadcaster loop skipped")
        return
    client = mqtt.Client(client_id=f"broadcaster-{STATION_ID}")
    client.on_connect = on_connect
    client.on_message = on_message
    log.info(f"Connecting MQTT {MQTT_HOST}:{MQTT_PORT} ...")
    client.connect(MQTT_HOST, MQTT_PORT, KEEPALIVE)
    client.loop_forever()


if __name__ == "__main__":
    main()
