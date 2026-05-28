"""
mission_orchestrator.py — Central Hub API Server
Flask → FastAPI 교체 (WebSocket 실시간 대시보드 지원)

API:
  POST /api/missions/broadcast     미션 브로드캐스트 배포
  GET  /api/missions/{id}/results  accept/reject 결과
  GET  /api/dashboard              대시보드 스냅샷
  GET  /api/redis                  Redis 키 조회 (디버그)
  GET  /api/mqtt-log               MQTT 수신 로그
  GET  /api/health                 헬스체크
  WS   /ws/dashboard               실시간 대시보드 스트림 (1초 주기)
  WS   /ws/mqtt                    MQTT 메시지 실시간 스트림
  GET  /                           React SPA 서브
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from threading import Thread
from typing import Set

import redis
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.config_loader import load_config

# FastAPI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# k8s
try:
    from kubernetes import client as k8s_client, config as k8s_config
    _K8S_OK = True
except ImportError:
    _K8S_OK = False

# paho-mqtt
try:
    import paho.mqtt.client as mqtt_lib
    _MQTT_OK = True
except ImportError:
    _MQTT_OK = False

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] hub: %(message)s")
log = logging.getLogger("central-hub")

cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}
        self._hashes = {}
        self._lists = {}

    def hset(self, key, field, value):
        self._hashes.setdefault(key, {})[field] = value

    def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def get(self, key):
        return self._strings.get(key)

    def exists(self, key):
        return key in self._strings or key in self._hashes or key in self._lists

    def expire(self, key, seconds):
        return True

    def keys(self, pattern):
        from fnmatch import fnmatch

        keys = list(self._strings) + list(self._hashes) + list(self._lists)
        return [key for key in keys if fnmatch(key, pattern)]

    def lrange(self, key, start, end):
        values = self._lists.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    def lpush(self, key, value):
        self._lists.setdefault(key, []).insert(0, value)

REDIS_HOST   = os.getenv("REDIS_HOST",  cfg.get("network.redis_host", "redis-service"))
REDIS_PORT   = int(os.getenv("REDIS_PORT", str(cfg.get("network.redis_port", 6379))))
NAMESPACE    = os.getenv("NAMESPACE",   cfg.get("network.namespace",   "default"))
SERVER_HOST  = cfg.get("network.bind_host", "0.0.0.0")
HUB_PORT     = int(cfg.get("network.hub_bind_port", 5000))
MQTT_HOST    = os.getenv("MQTT_HOST",   cfg.get("mqtt.host",  "localhost"))
MQTT_PORT_N  = int(os.getenv("MQTT_PORT", str(cfg.get("mqtt.port", 1883))))
K3S_DRY_RUN  = os.getenv("K3S_DRY_RUN", "0") == "1"

TOPIC_DEPLOY   = "fleet/mission/deploy"
TOPIC_ACCEPTED = "fleet/mission/accepted"

# ── Redis ─────────────────────────────────────────────────────────
r = MockRedis() if MOCK_MODE else redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# ── k8s ──────────────────────────────────────────────────────────
K3S_AVAILABLE = False
v1 = None
if _K8S_OK and not K3S_DRY_RUN and not MOCK_MODE:
    for loader in (k8s_config.load_incluster_config, k8s_config.load_kube_config):
        try:
            loader()
            K3S_AVAILABLE = True
            v1 = k8s_client.CoreV1Api()
            log.info("k8s config loaded")
            break
        except Exception:
            pass

# ── MQTT ─────────────────────────────────────────────────────────
_mqtt_log: list[dict] = []
_MQTT_LOG_MAX = 500
_mqtt_client = None
_mqtt_subscribed = False
_mqtt_ws_clients: Set[WebSocket] = set()   # MQTT WS 구독자


def _on_mqtt_connect(client, userdata, flags, rc):
    global _mqtt_subscribed
    if rc == 0 and not _mqtt_subscribed:
        client.subscribe([(TOPIC_ACCEPTED, 1), ("fleet/#", 0)])
        log.info("MQTT subscribed: fleet/#")
        _mqtt_subscribed = True


def _on_mqtt_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode()
        entry = {"topic": msg.topic, "payload": payload_str[:400], "ts": time.time()}
        _mqtt_log.append(entry)
        if len(_mqtt_log) > _MQTT_LOG_MAX:
            _mqtt_log.pop(0)

        # WS 브로드캐스트 (startup 이후에만 이벤트 루프에 태스크 전달)
        if _event_loop is not None and _event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _broadcast_mqtt(entry), _event_loop
            )
    except Exception:
        pass

    if msg.topic == TOPIC_ACCEPTED:
        try:
            p = json.loads(msg.payload.decode())
            r.hset(f"mission_result:{p.get('mission_id','?')}", p.get('robot_id','?'), msg.payload.decode())
            r.expire(f"mission_result:{p.get('mission_id','?')}", 3600)
        except Exception:
            pass

    if msg.topic.startswith("fleet/mission/cache/"):
        try:
            p = json.loads(msg.payload.decode())
            r.set(f"fleet:cache:{p.get('robot_id','?')}", msg.payload.decode(), ex=60)
        except Exception:
            pass

    # server heartbeat 갱신 (fallback_controller 감지용)
    r.set("fleet:server:heartbeat", "1", ex=15)


def _setup_mqtt():
    global _mqtt_client
    if not _MQTT_OK or MOCK_MODE:
        return
    try:
        _mqtt_client = mqtt_lib.Client(client_id="central-hub")
        _mqtt_client.on_connect = _on_mqtt_connect
        _mqtt_client.on_message = _on_mqtt_message
        _mqtt_client.connect(MQTT_HOST, MQTT_PORT_N, 60)
        _mqtt_client.loop_start()
        log.info(f"MQTT connected: {MQTT_HOST}:{MQTT_PORT_N}")
    except Exception as e:
        log.warning(f"MQTT connect failed: {e}")


if not MOCK_MODE:
    Thread(target=_setup_mqtt, daemon=True).start()

# ── FastAPI 앱 ────────────────────────────────────────────────────
app = FastAPI(title="Fleet Mission Hub", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path == "/" or path.endswith(".html") or path.startswith("/assets") or path.startswith("/favicon"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


app.add_middleware(NoCacheMiddleware)

# React SPA static 파일 (빌드 후 ui-spa/dist)
SPA_DIST = REPO_ROOT / "ui-spa" / "dist"
# Always mount the assets path so the server can serve built files that
# may be created after the process starts (previously mounting was
# conditional and would skip if `dist` didn't exist at import time).
app.mount("/assets", StaticFiles(directory=str(SPA_DIST / "assets")), name="assets")

# Fallback: keep the asset lookup anchored to the repository layout so the
# server works after the project is moved into a different workspace path.
FALLBACK_ASSETS = SPA_DIST / "assets"


@app.get("/assets/{asset_path:path}")
async def serve_assets(asset_path: str):
    target = FALLBACK_ASSETS / asset_path
    if target.exists() and target.is_file():
        return FileResponse(str(target))
    return JSONResponse({"detail": "Not Found"}, status_code=404)

_event_loop: asyncio.AbstractEventLoop = None
_dashboard_ws_clients: Set[WebSocket] = set()


@app.on_event("startup")
async def startup():
    global _event_loop
    _event_loop = asyncio.get_event_loop()
    # 대시보드 주기 브로드캐스트
    asyncio.create_task(_dashboard_broadcaster())


# ── WebSocket: 실시간 대시보드 ────────────────────────────────────
@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    _dashboard_ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # ping 유지
    except WebSocketDisconnect:
        _dashboard_ws_clients.discard(ws)


@app.websocket("/ws/mqtt")
async def ws_mqtt(ws: WebSocket):
    await ws.accept()
    _mqtt_ws_clients.add(ws)
    # 최근 50건 즉시 전송
    for entry in _mqtt_log[-50:]:
        try:
            await ws.send_json(entry)
        except Exception:
            break
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _mqtt_ws_clients.discard(ws)


async def _broadcast_mqtt(entry: dict):
    global _mqtt_ws_clients
    dead = set()
    for ws in list(_mqtt_ws_clients):
        try:
            await ws.send_json(entry)
        except Exception:
            dead.add(ws)
    _mqtt_ws_clients -= dead


async def _dashboard_broadcaster():
    """1초마다 대시보드 스냅샷을 모든 WS 클라이언트에 브로드캐스트."""
    global _dashboard_ws_clients
    while True:
        if _dashboard_ws_clients:
            snapshot = _build_dashboard()
            dead = set()
            for ws in list(_dashboard_ws_clients):
                try:
                    await ws.send_json(snapshot)
                except Exception:
                    dead.add(ws)
            _dashboard_ws_clients -= dead
        await asyncio.sleep(1)


# ── 대시보드 데이터 빌더 ──────────────────────────────────────────
def _build_dashboard() -> dict:
    result = {
        "mqtt_ok": _MQTT_OK and _mqtt_client is not None,
        "ts":      time.time(),
        "nodes":   [],
        "robots":  [],
        "rssi":    [],
        "handovers": [],
        "recent_missions": [],
        "checkpoints": [],
    }

    # k8s 노드 + Pod
    if K3S_AVAILABLE and v1:
        try:
            node_list = v1.list_node()
            pod_list  = v1.list_namespaced_pod(namespace=NAMESPACE)
            node_pods: dict[str, list] = {}
            for pod in pod_list.items:
                nn = pod.spec.node_name or "unknown"
                node_pods.setdefault(nn, []).append({
                    "name":  pod.metadata.name,
                    "app":   (pod.metadata.labels or {}).get("app", ""),
                    "phase": pod.status.phase or "Unknown",
                })
            for node in node_list.items:
                labels = node.metadata.labels or {}
                conds  = {c.type: c.status for c in (node.status.conditions or [])}
                ts     = node.metadata.creation_timestamp
                age_s  = int(time.time() - ts.timestamp()) if ts else 0
                result["nodes"].append({
                    "name":  node.metadata.name,
                    "role":  labels.get("node-role", "unknown"),
                    "ready": conds.get("Ready") == "True",
                    "age":   f"{age_s//3600}h{(age_s%3600)//60}m",
                    "pods":  node_pods.get(node.metadata.name, []),
                })
        except Exception as e:
            result["nodes_error"] = str(e)

    # 로봇 상태
    try:
        for key in r.keys("robot:*:status"):
            sn  = key.split(":")[1]
            raw = r.hgetall(key)
            if not raw: continue
            online_key = f"robot:{sn}:online"
            result["robots"].append({
                "robot_id":  sn,
                "online":    bool(r.exists(online_key)),
                "battery":   json.loads(raw.get("battery",  "{}")),
                "position":  json.loads(raw.get("position", "{}")),
                "speed":     json.loads(raw.get("speed",    "{}")),
                "imu":       json.loads(raw.get("imu",      "{}")),
                "armor":     json.loads(raw.get("armor",    "{}")),
                "esc_rpm":   json.loads(raw.get("esc_rpm",  "{}")),
                "current_mission": _safe_json(r.get(f"fleet:cache:{sn}")),
            })
    except Exception as e:
        result["robots_error"] = str(e)

    # RSSI (Phase 2)
    try:
        for key in r.keys("rssi:*:*"):
            raw = r.get(key)
            if raw:
                result["rssi"].append(json.loads(raw))
    except Exception:
        pass

    # 핸드오버 이벤트
    try:
        for key in r.keys("handover:*"):
            raw = r.get(key)
            if raw:
                result["handovers"].append(json.loads(raw))
    except Exception:
        pass

    # 미션 이력
    try:
        missions = []
        for key in sorted(r.keys("mission_result:*"))[-20:]:
            mid = key.replace("mission_result:", "")
            for rid, vs in r.hgetall(key).items():
                try:
                    v = json.loads(vs)
                    missions.append({"mission_id": mid, "robot_id": rid,
                                     "decision": v.get("decision","?"),
                                     "reason":   v.get("reason",""),
                                     "ts":       v.get("timestamp",0)})
                except Exception:
                    pass
        result["recent_missions"] = sorted(missions, key=lambda x: x["ts"], reverse=True)[:20]
    except Exception:
        pass

    # 체크포인트
    try:
        for key in r.keys("fleet:cache:*"):
            raw = r.get(key)
            if raw:
                result["checkpoints"].append(json.loads(raw))
    except Exception:
        pass

    return result


def _safe_json(raw):
    if not raw: return None
    try: return json.loads(raw)
    except Exception: return None


# ── REST API ─────────────────────────────────────────────────────
@app.post("/api/missions/broadcast")
async def broadcast_mission(body: dict):
    mission_name    = body.get("mission_name",    f"mission-{int(time.time())}")
    target_stations = body.get("target_stations", [])
    conditions      = body.get("conditions",      {})
    nodes           = body.get("nodes",           [])
    if not nodes:
        return JSONResponse({"status": "error", "message": "nodes required"}, 400)

    mission_id = f"mission-{int(time.time()*1000)}"
    payload    = {"mission_id": mission_id, "mission_name": mission_name,
                  "target_stations": target_stations, "conditions": conditions,
                  "nodes": nodes, "created_at": time.time()}
    r.set(f"mission:{mission_id}", json.dumps(payload), ex=86400)

    mqtt_sent = False
    if _mqtt_client and _MQTT_OK:
        try:
            _mqtt_client.publish(TOPIC_DEPLOY, json.dumps(payload), qos=1)
            mqtt_sent = True
        except Exception as e:
            log.warning(f"MQTT publish failed: {e}")

    return {"status": "success", "mission_id": mission_id,
            "mqtt_sent": mqtt_sent, "node_count": len(nodes)}


@app.post("/broadcast-mission")
async def broadcast_mission_alias(body: dict):
    """Legacy compatibility endpoint used by scripts and web UI tools.
    Proxies to the main `/api/missions/broadcast` handler.
    """
    return await broadcast_mission(body)


@app.get("/api/missions/{mission_id}/results")
async def get_mission_results(mission_id: str):
    raw = r.hgetall(f"mission_result:{mission_id}")
    results = {}
    for k, v in raw.items():
        try: results[k] = json.loads(v)
        except Exception: results[k] = v
    return {"mission_id": mission_id, "results": results}


@app.get("/api/dashboard")
async def get_dashboard():
    return _build_dashboard()


@app.get("/api/redis")
async def get_redis(key: str = ""):
    if not key:
        return JSONResponse({"error": "key required"}, 400)
    try:
        raw_hash = r.hgetall(key)
        if raw_hash:
            parsed = {}
            for k, v in raw_hash.items():
                try: parsed[k] = json.loads(v)
                except Exception: parsed[k] = v
            return {"key": key, "type": "hash", "value": parsed}
        raw_str = r.get(key)
        if raw_str:
            try: return {"key": key, "type": "string", "value": json.loads(raw_str)}
            except Exception: return {"key": key, "type": "string", "value": raw_str}
        raw_lst = r.lrange(key, 0, 19)
        if raw_lst:
            return {"key": key, "type": "list", "value": raw_lst}
        return {"key": key, "value": None}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@app.get("/api/mqtt-log")
async def get_mqtt_log(limit: int = 50):
    return {"logs": _mqtt_log[-limit:]}


@app.get("/api/health")
async def health():
    return {
        "k3s_available":  K3S_AVAILABLE,
        "mqtt_available": _MQTT_OK and _mqtt_client is not None,
        "namespace":      NAMESPACE,
        "hub_port":       HUB_PORT,
        "dry_run":        K3S_DRY_RUN,
    }


# ── React SPA 서브 ────────────────────────────────────────────────
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """API가 아닌 모든 경로 → React index.html (SPA 라우팅)"""
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        return JSONResponse({"error": "not found"}, 404)
    index = SPA_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
        # SPA가 빌드되지 않았을 때 간단한 상태 페이지 반환
        html = f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8" />
            <meta name="viewport" content="width=device-width,initial-scale=1" />
            <title>Fleet Mission Hub — UI not built</title>
            <style>
                body {{ background: #0f1117; color: #e6e6f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; padding: 24px; }}
                a {{ color: #7c6ff7; text-decoration: none; }}
                .card {{ background: #121318; border-radius: 8px; padding: 18px; max-width: 820px; box-shadow: 0 4px 14px rgba(0,0,0,0.6); }}
                h1 {{ color: #ffffff; margin: 0 0 8px 0; }}
                pre {{ background: #0b0c10; padding: 12px; border-radius: 6px; color: #dfe8ff; overflow:auto; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Fleet Mission Hub — UI not built</h1>
                <p>React SPA not found at <strong>ui-spa/dist/index.html</strong>.</p>
                <p>Build instructions:</p>
                <pre>cd ui-spa && npm install && npm run build</pre>
                <p>Server status and APIs:</p>
                <ul>
                    <li><a href="/api/health">/api/health</a></li>
                    <li><a href="/api/dashboard">/api/dashboard</a></li>
                </ul>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html, status_code=200)


# ── 진입점 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=HUB_PORT, log_level="info")
