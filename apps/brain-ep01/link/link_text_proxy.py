"""
link_text_proxy.py — EP01 경량 제어 어댑터 (robomaster SDK 불필요)

robomaster 파이썬 SDK(Python 3.8 고정) 없이, RoboMaster **평문 TCP SDK**(포트 40923)로
로봇을 제어하는 어댑터. 의존성은 **파이썬 표준 라이브러리뿐**이라 Python 3.13(라즈베리파이
trixie) 등 어디서나 바로 돈다. Redis도 내장 RESP 클라이언트로 접속하므로 pip 설치가 필요 없다.

프로토콜 계약(protocol/PROTOCOL.md v1)을 그대로 구현:
  - 명령 수신:  BLPOP robot:{SN}:commands   ({id,target,action,params})
  - 명령 결과:  RPUSH robot:{SN}:cmd_result ({id,target,action,status,error,ts})
  - 텔레메트리: HASH  robot:{SN}:status      (battery, _meta, ...)
  - 생존 신호:  SET   robot:{SN}:online 1 EX <ttl>

환경변수:
  ROBOT_IP    로봇 제어 IP (기본 192.168.2.1, AP 모드 게이트웨이)
  ROBOT_PORT  평문 SDK 포트 (기본 40923)
  ROBOT_SN    Redis 키 네임스페이스로 쓸 로봇 식별자
  ROBOT_TYPE  로봇 종류 (_meta.robot_type, 기본 ep01)
  REDIS_HOST / REDIS_PORT
  OFFLINE_TIMEOUT  online 키 TTL 초 (기본 10)
"""
import json
import logging
import os
import socket
import threading
import time

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] link_text: %(message)s")
log = logging.getLogger("link-text")

ROBOT_IP        = os.getenv("ROBOT_IP", "192.168.2.1")
ROBOT_PORT      = int(os.getenv("ROBOT_PORT", "40923"))
ROBOT_SN        = os.getenv("ROBOT_SN", "ep01-local")
ROBOT_TYPE      = os.getenv("ROBOT_TYPE", "ep01")
REDIS_HOST      = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT      = int(os.getenv("REDIS_PORT", "6379"))
OFFLINE_TIMEOUT = int(os.getenv("OFFLINE_TIMEOUT", "10"))

CMD_KEY     = f"robot:{ROBOT_SN}:commands"
STATUS_KEY  = f"robot:{ROBOT_SN}:status"
ONLINE_KEY  = f"robot:{ROBOT_SN}:online"
RESULT_KEY  = f"robot:{ROBOT_SN}:cmd_result"
RESULT_MAX  = 100
STATUS_TTL  = OFFLINE_TIMEOUT * 2
PROTOCOL_SCHEMA = 1


# ── 최소 Redis 클라이언트 (RESP, 표준 라이브러리만) ──────────────
class MiniRedis:
    """BLPOP/RPUSH/HSET/SET/EXPIRE/DEL/LTRIM만 지원하는 경량 RESP 클라이언트."""

    def __init__(self, host, port):
        self.host, self.port = host, port
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        self.buf = b""

    def _readline(self):
        while b"\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("redis closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\r\n", 1)
        return line

    def _read_reply(self):
        line = self._readline()
        t, rest = line[:1], line[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            raise RuntimeError(rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n == -1:
                return None
            while len(self.buf) < n + 2:
                self.buf += self.sock.recv(4096)
            data, self.buf = self.buf[:n], self.buf[n + 2:]
            return data.decode()
        if t == b"*":
            n = int(rest)
            if n == -1:
                return None
            return [self._read_reply() for _ in range(n)]
        raise RuntimeError(f"unexpected reply: {line!r}")

    def cmd(self, *args, timeout=None):
        payload = f"*{len(args)}\r\n".encode()
        for a in args:
            a = str(a).encode()
            payload += f"${len(a)}\r\n".encode() + a + b"\r\n"
        with self._lock:
            self.sock.settimeout(timeout)
            self.sock.sendall(payload)
            return self._read_reply()

    # 편의 메서드
    def ping(self):        return self.cmd("PING")
    def rpush(self, k, v): return self.cmd("RPUSH", k, v)
    def hset(self, k, f, v): return self.cmd("HSET", k, f, v)
    def expire(self, k, s): return self.cmd("EXPIRE", k, s)
    def setex(self, k, s, v): return self.cmd("SET", k, v, "EX", s)
    def delete(self, k):   return self.cmd("DEL", k)
    def ltrim(self, k, a, b): return self.cmd("LTRIM", k, a, b)

    def blpop(self, k, timeout):
        # BLPOP은 블로킹이므로 소켓 타임아웃을 여유있게 준다.
        return self.cmd("BLPOP", k, timeout, timeout=timeout + 5)


# ── RoboMaster 평문 SDK 연결 ─────────────────────────────────────
class RobotText:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        self.sock = socket.create_connection((self.ip, self.port), timeout=6)
        self.sock.settimeout(8)
        self._send("command")   # SDK 모드 진입
        log.info(f"로봇 평문 SDK 연결: {self.ip}:{self.port}")

    def _send(self, line):
        with self._lock:
            self.sock.sendall((line + ";").encode())
            try:
                return self.sock.recv(2048).decode(errors="ignore").strip()
            except socket.timeout:
                return "(timeout)"

    def send(self, line):
        try:
            return self._send(line)
        except (OSError, ConnectionError):
            log.warning("로봇 연결 끊김 — 재연결 시도")
            self._connect()
            return self._send(line)


# {target, action, params} → 평문 명령 목록으로 번역 (EP01)
def translate(target, action, p):
    if target == "chassis":
        if action == "MOVE":
            return [f"chassis move x {p.get('x',0)} y {p.get('y',0)} z 0 vxy {p.get('speed',0.5)}"]
        if action == "ROTATE":
            return [f"chassis move x 0 y 0 z {p.get('yaw',0)} vz {p.get('v_speed',45)}"]
        if action == "STOP":
            return ["chassis speed x 0 y 0 z 0"]
    if target == "led" and action == "SET":
        return [f"led control comp all r {p.get('r',255)} g {p.get('g',255)} b {p.get('b',255)} effect solid"]
    if target == "actuator":
        if action == "GRIPPER":
            opened = bool(p.get("open", False)) or p.get("grip") == "open"
            return [f"robotic_gripper {'open' if opened else 'close'} 1"]
        if action == "ARM_MOVE":
            return [f"robotic_arm moveto x {p.get('arm_x',0)} y {p.get('arm_y',0)}"]
    if target == "flow":
        # 흐름 제어는 상위(listener)에서 전개되므로 장치 명령이 아니다 → no-op ack
        return []
    return None   # 미지원


def heartbeat_loop(rds, robot):
    while True:
        try:
            rds.setex(ONLINE_KEY, OFFLINE_TIMEOUT, "1")
            rds.hset(STATUS_KEY, "_meta", json.dumps(
                {"robot_type": ROBOT_TYPE, "schema": PROTOCOL_SCHEMA, "ts": time.time()}))
            rds.expire(STATUS_KEY, STATUS_TTL)
            # 배터리 조회 (평문 SDK) — 실패해도 무시
            try:
                resp = robot.send("battery ?")
                soc = int(float(resp.replace(";", "").strip().split()[0]))
                rds.hset(STATUS_KEY, "battery", json.dumps({"soc": soc}))
            except Exception:
                pass
        except Exception as e:
            log.debug(f"heartbeat 실패: {e}")
        time.sleep(max(1, OFFLINE_TIMEOUT // 2))


def ack(rds, cmd, status, error=None):
    try:
        rds.rpush(RESULT_KEY, json.dumps({
            "id":     cmd.get("id", ""),
            "target": cmd.get("target", ""),
            "action": cmd.get("action", ""),
            "status": status,
            "error":  error,
            "ts":     time.time(),
        }))
        rds.ltrim(RESULT_KEY, -RESULT_MAX, -1)
        rds.expire(RESULT_KEY, STATUS_TTL)
    except Exception as e:
        log.debug(f"ack 기록 실패: {e}")


def handle(rds, robot, cmd):
    target = cmd.get("target", "")
    action = cmd.get("action", "")
    params = cmd.get("params", {}) or {}
    lines = translate(target, action, params)
    if lines is None:
        log.warning(f"미지원 명령: {target}.{action}")
        ack(rds, cmd, "error", f"unsupported: {target}.{action}")
        return
    try:
        for line in lines:
            resp = robot.send(line)
            log.info(f"{target}.{action} -> [{line}] resp={resp}")
            if resp and "fail" in resp.lower():
                ack(rds, cmd, "error", resp)
                return
        ack(rds, cmd, "ok")
    except Exception as e:
        log.error(f"{target}.{action} 실패: {e}")
        ack(rds, cmd, "error", str(e))


def main():
    log.info(f"link_text_proxy 시작 — SN={ROBOT_SN} robot={ROBOT_IP}:{ROBOT_PORT} "
             f"redis={REDIS_HOST}:{REDIS_PORT}")
    robot = RobotText(ROBOT_IP, ROBOT_PORT)
    rds = MiniRedis(REDIS_HOST, REDIS_PORT)
    rds.ping()
    log.info("Redis 연결 OK")

    threading.Thread(target=heartbeat_loop, args=(rds, robot), daemon=True).start()
    log.info(f"명령 대기 — {CMD_KEY}")

    # 별도 연결로 BLPOP(블로킹) 전용 사용 (heartbeat와 소켓 분리)
    blocker = MiniRedis(REDIS_HOST, REDIS_PORT)
    while True:
        try:
            res = blocker.blpop(CMD_KEY, timeout=5)
            if not res:
                continue
            _, raw = res
            handle(rds, robot, json.loads(raw))
        except Exception as e:
            log.error(f"명령 루프 에러: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
