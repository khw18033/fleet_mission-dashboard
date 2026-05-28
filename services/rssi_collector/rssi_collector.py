"""
rssi_collector.py — 기지국 RPi (edge role) 에서 실행
iw dev {interface} scan 으로 주변 로봇 AP RSSI 수집 → EWMA 평활화 → Redis 저장

Redis 키: rssi:{station_id}:{robot_sn}
값: {"rssi": -65, "ewma": -67.2, "ssid": "RMEP-1088dc", "ts": 1234567890}

환경변수:
  STATION_ID       기지국 ID (예: station-a)
  SCAN_INTERFACE   스캔 인터페이스 (기본 wlan1)
  REDIS_HOST
  REDIS_PORT
"""
import json, logging, os, re, subprocess, sys, time
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.config_loader import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] rssi_collector: %(message)s",
)
log = logging.getLogger("rssi-collector")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}

    def ping(self):
        return True

    def set(self, key, value, ex=None):
        self._strings[key] = value

STATION_ID  = os.getenv("STATION_ID",     "station-a")
INTERFACE   = os.getenv("SCAN_INTERFACE", "wlan1")
REDIS_HOST  = os.getenv("REDIS_HOST",     cfg.get("network.redis_host", "redis-service"))
REDIS_PORT  = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))

SCAN_INTERVAL = float(cfg.get("services.rssi.scan_interval_sec", 3))
EWMA_ALPHA    = float(cfg.get("services.rssi.ewma_alpha",        0.3))
REDIS_TTL     = int(cfg.get("services.rssi.redis_ttl_sec",       30))
SSID_PREFIX   = cfg.get("robot.ap.ssid_prefix", "RMEP-")
SSID_TO_SN    = cfg.get("robot.ap.ssid_to_sn",  {}) or {}

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

# EWMA 상태 저장 (메모리)
_ewma: dict[str, float] = {}


def scan_rssi() -> dict[str, dict]:
    """
    iw dev {interface} scan 실행 후 RMEP- 패턴 SSID의 RSSI 파싱.
    반환: {ssid: {"rssi": -65, "sn": "3JKCK5L003093S"}}
    """
    results: dict[str, dict] = {}
    if MOCK_MODE:
        mock_ssid = next(iter(SSID_TO_SN.keys()), f"{SSID_PREFIX}mock")
        mock_sn = SSID_TO_SN.get(mock_ssid, next(iter(SSID_TO_SN.values()), "mock-sn"))
        return {mock_ssid: {"rssi": -55.0, "sn": mock_sn}}
    try:
        out = subprocess.check_output(
            ["iw", "dev", INTERFACE, "scan"],
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode(errors="ignore")
    except subprocess.TimeoutExpired:
        log.warning("iw scan timeout")
        return results
    except subprocess.CalledProcessError as e:
        log.warning(f"iw scan 실패 (권한 또는 인터페이스 확인): {e}")
        return results
    except FileNotFoundError:
        log.error("iw 명령어 없음 — NET_ADMIN capability 및 iw 패키지 확인")
        return results

    # BSS 블록 단위로 파싱
    current_ssid: str | None = None
    current_rssi: float | None = None

    for line in out.splitlines():
        line = line.strip()

        # SSID 감지
        m = re.match(r"SSID:\s*(.+)", line)
        if m:
            current_ssid = m.group(1).strip()

        # signal 감지 (dBm)
        m = re.match(r"signal:\s*([-\d.]+)\s*dBm", line)
        if m:
            current_rssi = float(m.group(1))

        # BSS 블록 끝 감지 (새 BSS 시작 또는 파일 끝)
        if line.startswith("BSS ") and current_ssid and current_rssi is not None:
            if current_ssid.startswith(SSID_PREFIX):
                sn = SSID_TO_SN.get(current_ssid, current_ssid)
                results[current_ssid] = {"rssi": current_rssi, "sn": sn}
            current_ssid = None
            current_rssi = None

    # 마지막 블록 처리
    if current_ssid and current_rssi is not None and current_ssid.startswith(SSID_PREFIX):
        sn = SSID_TO_SN.get(current_ssid, current_ssid)
        results[current_ssid] = {"rssi": current_rssi, "sn": sn}

    return results


def apply_ewma(ssid: str, raw_rssi: float) -> float:
    """EWMA 평활화: ewma = alpha * raw + (1 - alpha) * prev"""
    if ssid not in _ewma:
        _ewma[ssid] = raw_rssi
    else:
        _ewma[ssid] = EWMA_ALPHA * raw_rssi + (1 - EWMA_ALPHA) * _ewma[ssid]
    return round(_ewma[ssid], 2)


def store(ssid: str, sn: str, raw_rssi: float, ewma: float) -> None:
    key  = f"rssi:{STATION_ID}:{sn}"
    data = {
        "rssi":    raw_rssi,
        "ewma":    ewma,
        "ssid":    ssid,
        "station": STATION_ID,
        "sn":      sn,
        "ts":      time.time(),
    }
    r.set(key, json.dumps(data), ex=REDIS_TTL)
    log.info(f"  {ssid} ({sn}): raw={raw_rssi} dBm  ewma={ewma} dBm")


def main():
    log.info(f"RSSI Collector 시작 — station={STATION_ID} iface={INTERFACE} interval={SCAN_INTERVAL}s")
    log.info(f"SSID 매핑: {SSID_TO_SN}")

    if MOCK_MODE:
        log.info("MOCK_MODE=1 — scan loop skipped")
        return

    while True:
        try:
            results = scan_rssi()
            if results:
                for ssid, info in results.items():
                    ewma = apply_ewma(ssid, info["rssi"])
                    store(ssid, info["sn"], info["rssi"], ewma)
            else:
                log.debug("감지된 로봇 AP 없음")
        except Exception as e:
            log.error(f"스캔 루프 에러: {e}", exc_info=True)

        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    main()
