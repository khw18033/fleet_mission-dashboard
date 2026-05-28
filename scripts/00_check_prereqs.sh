#!/usr/bin/env bash
# 00_check_prereqs.sh — 테스트 시작 전 필수 도구 및 환경 점검
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "사전 요구사항 점검"
FAIL=0

check_cmd() {
  local cmd="$1" label="${2:-$1}"
  if command -v "$cmd" &>/dev/null; then
    ok "$label ($(command -v "$cmd"))"
  else
    err "$label 없음"
    FAIL=1
  fi
}

# ── 시스템 도구 ──────────────────────────────────────────────────
section "시스템 도구"
check_cmd kubectl       "kubectl"
check_cmd docker        "Docker"
check_cmd python3       "Python3"
check_cmd node          "Node.js (React SPA 빌드용)"
check_cmd npm           "npm"
check_cmd mosquitto_pub "mosquitto-clients"

# ── Python 패키지 ─────────────────────────────────────────────────
section "Python 패키지"
PKGS=(fastapi uvicorn paho redis yaml kubernetes requests)
for pkg in "${PKGS[@]}"; do
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "  $pkg"
  else
    warn "  $pkg 없음 — pip install $pkg"
    FAIL=1
  fi
done

# streamlit은 레거시 — 없어도 경고만
if python3 -c "import streamlit" 2>/dev/null; then
  info "  streamlit (레거시 — 미사용)"
fi

# ── k3s 클러스터 ─────────────────────────────────────────────────
section "k3s 클러스터"
if kubectl cluster-info &>/dev/null; then
  ok "k3s 연결됨"
  kubectl get nodes -L node-role -o wide
else
  err "k3s 클러스터 연결 불가"
  FAIL=1
fi

# ── MQTT 브로커 ───────────────────────────────────────────────────
section "MQTT 브로커 (${MQTT_HOST}:${MQTT_PORT})"
if mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" \
     -t "fleet/ping" -m "check" -q 0 2>/dev/null; then
  ok "MQTT 브로커 응답"
else
  warn "MQTT 브로커 응답 없음"
  warn "  확인: mosquitto가 ${MQTT_HOST}:${MQTT_PORT}에서 실행 중인지"
fi

# ── config.yaml 주요 값 ───────────────────────────────────────────
section "config.yaml 점검"
info "hub_host   = $(cfg network.hub_host)"
info "hub_port   = $(cfg network.hub_port)"
info "mqtt_host  = $MQTT_HOST"
info "namespace  = $NAMESPACE"
info "robot_sn   = $(cfg runtime.default_robot_sn)"
info "conn_type  = $(cfg link.conn_type)"

# ── ui-spa 빌드 상태 ─────────────────────────────────────────────
section "React SPA 빌드 상태"
if [[ -d "ui-spa/dist" ]]; then
  ok "ui-spa/dist 존재 (이미 빌드됨)"
else
  warn "ui-spa/dist 없음 — 첫 실행 시 자동 빌드"
  warn "  수동 빌드: cd ui-spa && npm install && npm run build"
fi

# ── 결과 ─────────────────────────────────────────────────────────
section "점검 결과"
if [[ $FAIL -eq 0 ]]; then
  ok "모든 필수 항목 통과"
  info "다음 단계: bash scripts/01_label_nodes.sh"
else
  err "일부 항목 실패 — 위 항목 해결 후 재실행"
  echo ""
  info "빠른 설치:"
  info "  pip install fastapi uvicorn paho-mqtt redis pyyaml kubernetes requests"
  info "  apt install mosquitto-clients  (또는 brew install mosquitto)"
  exit 1
fi
