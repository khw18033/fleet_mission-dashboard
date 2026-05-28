#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

DEV="${DEV:-0}"
WEBUI_PORT="${WEBUI_PORT:-5001}"

export HUB_BIND_PORT="$WEBUI_PORT"
export NAMESPACE="${NAMESPACE:-centralized}"

section "Fleet Mission UI 실행"

if [[ "$DEV" == "1" ]]; then
  info "개발 모드 — Vite(:5173) + FastAPI(:${WEBUI_PORT})"
  info "UI: http://localhost:5173"
  info "API: http://localhost:${WEBUI_PORT}"

  python3 -m uvicorn apps.central-hub.mission_orchestrator:app \
    --host 0.0.0.0 --port "$WEBUI_PORT" --reload &
  API_PID=$!

  cd ui-spa
  VITE_API_TARGET="${VITE_API_TARGET:-http://127.0.0.1:${WEBUI_PORT}}" npm run dev

  kill "$API_PID" 2>/dev/null || true
else
  if [[ ! -d "ui-spa/dist" ]]; then
    warn "ui-spa/dist 없음 — React 빌드 시작..."
    (cd ui-spa && npm install && npm run build)
    ok "React 빌드 완료"
  fi

  info "프로덕션 모드"
  info "URL: http://localhost:${WEBUI_PORT}"
  info "종료: Ctrl+C"

  python3 -m uvicorn apps.central-hub.mission_orchestrator:app \
    --host 0.0.0.0 --port "$WEBUI_PORT" --log-level info
fi
