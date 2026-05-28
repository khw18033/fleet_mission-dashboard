"""
link_proxy.py — EP01 로봇 직접 제어 브릿지

핵심 유지:
  - Redis command queue: robot:{ROBOT_SN}:commands
  - Redis status hash:   robot:{ROBOT_SN}:status
  - Redis event pubsub:  robot:{ROBOT_SN}:event:{event_type}
  - Redis online key:    robot:{ROBOT_SN}:online

문제 해결 수정:
  - RoboMaster AP 모드는 config 값과 무관하게 real_conn_type="ap"로 강제
  - LOCAL_IP 환경변수를 robomaster.config.LOCAL_IP_STR에 명시 적용
  - rm-test2에서 성공한 연결 순서와 동일하게 initialize 수행
  - 연결 실패 시 프로세스 종료 대신 20초 후 재시도
"""

import os
import time
import logging
import sys
import json
import math
import redis
from threading import Thread, Event

MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"

if MOCK_MODE:
    class _MockRobotConfig:
        LOCAL_IP_STR = ""

    class _MockRobotAPI:
        class Robot:
            def initialize(self, *args, **kwargs):
                return True

            def close(self):
                return None

            def set_robot_mode(self, *args, **kwargs):
                return None

            class battery:
                @staticmethod
                def sub_battery_info(*args, **kwargs):
                    return None

            class chassis:
                @staticmethod
                def sub_position(*args, **kwargs):
                    return None

                @staticmethod
                def sub_velocity(*args, **kwargs):
                    return None

                @staticmethod
                def sub_imu(*args, **kwargs):
                    return None

                @staticmethod
                def sub_esc(*args, **kwargs):
                    return None

                @staticmethod
                def move(*args, **kwargs):
                    class _Done:
                        def wait_for_completed(self):
                            return None
                    return _Done()

                @staticmethod
                def drive_speed(*args, **kwargs):
                    return None

            class gripper:
                @staticmethod
                def open(*args, **kwargs):
                    return None

                @staticmethod
                def close(*args, **kwargs):
                    return None

            class robotic_arm:
                @staticmethod
                def move(*args, **kwargs):
                    class _Done:
                        def wait_for_completed(self):
                            return None
                    return _Done()

            class led:
                @staticmethod
                def set_led(*args, **kwargs):
                    return None

            class armor:
                @staticmethod
                def sub_hit_event(*args, **kwargs):
                    return None

    robomaster = _MockRobotAPI()
    robomaster_robot = robomaster
    robomaster_config = _MockRobotConfig()
else:
    import robomaster
    from robomaster import robot as robomaster_robot
    from robomaster import config as robomaster_config


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.config_loader import load_config

cfg = load_config()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] link_proxy: %(message)s",
)
log = logging.getLogger("link-proxy")


TARGET_IP = os.getenv("ROBOT_IP", "192.168.2.1")
LOCAL_IP = os.getenv("LOCAL_IP", "")
ROBOT_ID = os.getenv("ROBOT_SN", cfg.get("runtime.default_robot_sn", "ep01"))
ROBOT_TYPE = os.getenv("ROBOT_TYPE", "ep01")

REDIS_HOST = os.getenv("REDIS_HOST", cfg.get("network.redis_host", "redis-service"))
REDIS_PORT = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))

# config 값은 로그에만 남긴다. 실제 SDK 연결은 AP로 강제한다.
CONFIG_CONN_TYPE = cfg.get("link.conn_type", "ap")
REAL_CONN_TYPE = "ap"

CMD_TIMEOUT = int(cfg.get("timeouts.redis_command_wait_sec", 5))
BATTERY_FREQ = int(cfg.get("services.link.sensor_frequencies.battery_hz", 1))
POSITION_FREQ = int(cfg.get("services.link.sensor_frequencies.position_hz", 5))
VELOCITY_FREQ = int(cfg.get("services.link.sensor_frequencies.velocity_hz", 5))
IMU_FREQ = int(cfg.get("services.link.sensor_frequencies.imu_hz", 2))
ESC_FREQ = int(cfg.get("services.link.sensor_frequencies.esc_hz", 2))

OFFLINE_TIMEOUT = int(cfg.get("robot.offline_timeout_sec", 10))
STATUS_TTL = OFFLINE_TIMEOUT * 2
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "20"))

CMD_KEY = f"robot:{ROBOT_ID}:commands"
STATUS_KEY = f"robot:{ROBOT_ID}:status"
EVT_PREFIX = f"robot:{ROBOT_ID}:event"
ONLINE_KEY = f"robot:{ROBOT_ID}:online"

ARMOR_POS = {1: "back", 2: "front", 3: "left", 4: "right"}


try:
    if MOCK_MODE:
        class MockRedis:
            def __init__(self):
                self._strings = {}
                self._hashes = {}
                self._lists = {}

            def ping(self): return True
            def hset(self, key, field, value): self._hashes.setdefault(key, {})[field] = value
            def hget(self, key, field): return self._hashes.get(key, {}).get(field)
            def expire(self, key, ttl): return True
            def publish(self, channel, payload): return True
            def set(self, key, value, ex=None): self._strings[key] = value
            def delete(self, key): self._strings.pop(key, None); self._hashes.pop(key, None)
            def blpop(self, key, timeout=0): return None
            def pubsub(self):
                class _PS:
                    def subscribe(self, *args, **kwargs): return None
                    def listen(self):
                        if False:
                            yield None
                    def unsubscribe(self): return None
                return _PS()

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


class RobotLinkProxy:
    def __init__(self, ep):
        self.ep = ep

    def _hset(self, field: str, data: dict):
        try:
            r.hset(STATUS_KEY, field, json.dumps(data))
            r.expire(STATUS_KEY, STATUS_TTL)
        except Exception as e:
            log.debug(f"hset 실패 ({field}): {e}")

    def _publish(self, event_type: str, data: dict):
        try:
            r.publish(f"{EVT_PREFIX}:{event_type}", json.dumps(data))
        except Exception as e:
            log.debug(f"publish 실패 ({event_type}): {e}")

    def heartbeat_loop(self):
        while True:
            try:
                r.set(ONLINE_KEY, "1", ex=OFFLINE_TIMEOUT)
            except Exception as e:
                log.debug(f"heartbeat 실패: {e}")
            time.sleep(max(1, OFFLINE_TIMEOUT // 2))

    def mark_offline(self):
        try:
            r.delete(ONLINE_KEY)
            r.delete(STATUS_KEY)
            log.info(f"Robot {ROBOT_ID} → offline (Redis 키 삭제)")
        except Exception as e:
            log.debug(f"offline 마킹 실패: {e}")

    def on_battery(self, info):
        self._hset("battery", {"soc": info})

    def on_position(self, pos_info):
        x, y, _ = pos_info
        self._hset("position", {"x": round(x, 3), "y": round(y, 3)})

    def on_velocity(self, vel_info):
        vgx, vgy = vel_info[:2]
        speed = math.sqrt(vgx**2 + vgy**2)
        self._hset(
            "speed",
            {
                "speed": round(speed, 2),
                "vx": round(vgx, 2),
                "vy": round(vgy, 2),
            },
        )

    def on_imu(self, imu_info):
        acc = [round(v, 3) for v in imu_info[0:3]]
        self._hset("imu", {"ax": acc[0], "ay": acc[1], "az": acc[2]})

    def on_esc(self, esc_info):
        rpms = [m[0] for m in esc_info]
        self._hset("esc_rpm", {"wheels": rpms})

    def on_armor_hit(self, armor_info):
        armor_id, hit_type = armor_info
        data = {
            "id": armor_id,
            "type": hit_type,
            "position": ARMOR_POS.get(armor_id, str(armor_id)),
            "ts": time.time(),
        }
        self._hset("armor", data)
        self._publish("armor_hit", data)
        log.info(f"Armor hit: id={armor_id} pos={data['position']}")

    def command_loop(self):
        log.info(f"명령 대기 — {CMD_KEY}")
        while True:
            try:
                res = r.blpop(CMD_KEY, timeout=CMD_TIMEOUT)
                if res:
                    _, raw = res
                    self.execute(json.loads(raw))
            except Exception as e:
                log.error(f"command_loop 에러: {e}")
                time.sleep(1)

    def execute(self, cmd: dict):
        target = cmd.get("target", "")
        action = cmd.get("action", "")
        p = cmd.get("params", {})

        log.info(f"▶ {target}.{action}  params={p}")

        try:
            if target == "flow":
                self._exec_flow(action, cmd)

            elif target == "chassis":
                if action == "MOVE":
                    self.ep.chassis.move(
                        x=float(p.get("x", 0)),
                        y=float(p.get("y", 0)),
                        z=float(p.get("z", 0)),
                        xy_speed=float(p.get("speed", 0.5)),
                    ).wait_for_completed()
                elif action == "ROTATE":
                    self.ep.chassis.move(
                        x=0,
                        y=0,
                        z=float(p.get("yaw", 0)),
                        z_speed=float(p.get("v_speed", 45)),
                    ).wait_for_completed()
                elif action == "STOP":
                    self.ep.chassis.drive_speed(x=0, y=0, z=0)

            elif target == "actuator":
                if action == "GRIPPER":
                    pwr = max(1, int(p.get("grip_p", p.get("power", 50))))
                    if bool(p.get("open", False)) or p.get("grip") == "open":
                        self.ep.gripper.open(power=pwr)
                    else:
                        self.ep.gripper.close(power=pwr)
                    time.sleep(1.5)

                elif action == "ARM_MOVE":
                    self.ep.robotic_arm.move(
                        x=float(p.get("arm_x", 0)),
                        y=float(p.get("arm_y", 0)),
                    ).wait_for_completed()

            elif target == "led":
                if action == "SET":
                    self.ep.led.set_led(
                        comp="all",
                        r=int(p.get("r", 255)),
                        g=int(p.get("g", 255)),
                        b=int(p.get("b", 255)),
                        effect=str(p.get("eff", "on")),
                    )

            else:
                log.warning(f"알 수 없는 target: {target}")

            log.info(f"✅ {target}.{action} 완료")

        except Exception as e:
            log.error(f"❌ {target}.{action} 실패: {e}", exc_info=True)

    def _exec_flow(self, action: str, cmd: dict):
        if action == "REPEAT":
            times = int(cmd.get("params", {}).get("times", 1))
            body = cmd.get("body", [])
            for _ in range(times):
                for sub in body:
                    self.execute(sub)

        elif action == "IF":
            met = self._eval_condition(cmd.get("condition", {}))
            branch = cmd.get("then", []) if met else cmd.get("else", [])
            for sub in branch:
                self.execute(sub)

        elif action == "WAIT_EVENT":
            event_type = cmd.get("event", "armor_hit")
            filter_p = cmd.get("params", {})
            timeout_sec = float(cmd.get("timeout_sec", 10))
            triggered = Event()

            def _check(data):
                return all(str(data.get(k)) == str(v) for k, v in filter_p.items())

            ps = r.pubsub()
            ps.subscribe(f"{EVT_PREFIX}:{event_type}")

            def _listen():
                for msg in ps.listen():
                    if msg["type"] == "message":
                        try:
                            if _check(json.loads(msg["data"])):
                                triggered.set()
                                break
                        except Exception:
                            pass

            Thread(target=_listen, daemon=True).start()
            fired = triggered.wait(timeout=timeout_sec)
            ps.unsubscribe()
            log.info(f"  WAIT_EVENT '{event_type}' → {'발생' if fired else 'timeout'}")

        else:
            log.warning(f"알 수 없는 flow action: {action}")

    def _eval_condition(self, cond: dict) -> bool:
        sensor = cond.get("sensor", "")
        field = cond.get("field", "")
        op = cond.get("op", "eq")
        value = cond.get("value")

        try:
            raw = r.hget(STATUS_KEY, sensor)
            if not raw:
                return False

            data = json.loads(raw)
            actual = data.get(field)

            if actual is None:
                return False

            try:
                an = float(actual)
                vn = float(value)
                numeric = True
            except Exception:
                an = vn = 0
                numeric = False

            return {
                "eq": str(actual) == str(value),
                "ne": str(actual) != str(value),
                "gt": numeric and an > vn,
                "lt": numeric and an < vn,
                "gte": numeric and an >= vn,
                "lte": numeric and an <= vn,
            }.get(op, False)

        except Exception as e:
            log.debug(f"조건 평가 실패: {e}")
            return False


def connect_robot():
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — robot connection skipped")
        return None
    if LOCAL_IP:
        robomaster_config.LOCAL_IP_STR = LOCAL_IP
        log.info(f"RoboMaster LOCAL_IP_STR={LOCAL_IP}")

    log.info(
        "로봇 연결 중 — "
        f"IP={TARGET_IP} "
        f"SN={ROBOT_ID} "
        f"robot_type={ROBOT_TYPE} "
        f"cfg_conn={CONFIG_CONN_TYPE} "
        f"real_conn={REAL_CONN_TYPE}"
    )

    ep = robomaster_robot.Robot()

    ok = ep.initialize(
        conn_type=REAL_CONN_TYPE,
        sn=ROBOT_ID,
    )

    log.info(f"RoboMaster initialize result={ok}")

    if not ok:
        try:
            ep.close()
        except Exception:
            pass
        return None

    try:
        ep.set_robot_mode(mode="free")
        log.info("set_robot_mode free OK")
    except Exception as e:
        log.warning(f"set_robot_mode 실패: {e}")

    return ep


def start_proxy():
    if MOCK_MODE:
        log.info("MOCK_MODE=1 — link_proxy hardware loop skipped")
        return
    while True:
        ep = None
        proxy = None

        try:
            ep = connect_robot()

            if ep is None:
                log.error(f"로봇 초기화 실패 — {RECONNECT_DELAY}초 후 재시도")
                time.sleep(RECONNECT_DELAY)
                continue

            log.info("로봇 연결 성공 ✅")
            proxy = RobotLinkProxy(ep)

            try:
                ep.battery.sub_battery_info(freq=BATTERY_FREQ, callback=proxy.on_battery)
                ep.chassis.sub_position(freq=POSITION_FREQ, callback=proxy.on_position)
                ep.chassis.sub_velocity(freq=VELOCITY_FREQ, callback=proxy.on_velocity)
                ep.chassis.sub_imu(freq=IMU_FREQ, callback=proxy.on_imu)
                ep.chassis.sub_esc(freq=ESC_FREQ, callback=proxy.on_esc)
            except Exception as e:
                log.warning(f"센서 구독 일부 실패: {e}", exc_info=True)

            try:
                ep.armor.sub_hit_event(callback=proxy.on_armor_hit)
                log.info("Armor hit 이벤트 구독 완료")
            except Exception as e:
                log.warning(f"Armor 구독 실패: {e}")

            Thread(target=proxy.heartbeat_loop, daemon=True).start()
            Thread(target=proxy.command_loop, daemon=True).start()

            log.info(f"Link Proxy 가동 — cmd: {CMD_KEY} / online: {ONLINE_KEY}")

            while True:
                time.sleep(1)

        except Exception as e:
            log.error(f"로봇 연결/운영 예외: {e}", exc_info=True)
            time.sleep(RECONNECT_DELAY)

        finally:
            if proxy:
                proxy.mark_offline()

            if ep:
                try:
                    ep.close()
                    log.info("로봇 연결 종료")
                except Exception:
                    pass


if __name__ == "__main__":
    start_proxy()