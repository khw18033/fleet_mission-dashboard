#!/usr/bin/env bash
# 09_test_pipeline.sh — Phase 1 E2E 파이프라인 테스트
#
# 테스트 케이스:
#   TEST A: robot_type=ep01 조건 → accept 확인 + 로봇 실제 동작
#   TEST B: robot_type=go1  조건 → reject 확인 (EP01에서 거부)
#   TEST C: min_battery=999 조건 → reject 확인 (배터리 부족)
set -euo pipefail
source "$(dirname "$0")/common.sh"

# ── 설정 ────────────────────────────────────────────────────────
HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
  -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "localhost")
HUB_NODE_PORT="$(cfg kubernetes.node_port)"
HUB_URL="http://${HUB_NODE}:${HUB_NODE_PORT}"

WAIT_SEC=10
LOG_DIR="/tmp/fleet-test-$(date +%s)"
mkdir -p "$LOG_DIR"

ROBOT_TYPE_CFG="$(cfg robot.type)"      # config.yaml의 실제 로봇 타입 (ep01)

info "Hub URL:     $HUB_URL"
info "MQTT:        ${MQTT_HOST}:${MQTT_PORT}"
info "Robot type:  ${ROBOT_TYPE_CFG}"
info "Log dir:     $LOG_DIR"

# ── MQTT 구독 백그라운드 시작 ────────────────────────────────────
section "MQTT 구독 리스너 시작"
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/#" -v \
  > "$LOG_DIR/mqtt_all.log" 2>&1 &
MQTT_PID=$!
sleep 1
ok "MQTT 리스너 시작 (PID $MQTT_PID)"

# ── 공통 브로드캐스트 함수 ───────────────────────────────────────
broadcast_mission() {
  local label="$1"
  local robot_type="$2"
  local min_battery="${3:-0}"
  local extra_nodes="${4:-}"

  local mission_name="test-${label}-$(date +%s)"

  # LED on + 짧은 이동 (EP01 기본 테스트 노드)
  local nodes
  nodes=$(cat <<EOF
[
  {
    "target": "led",
    "action": "SET",
    "params": {"r": 0, "g": 255, "b": 0, "eff": "on"},
    "delay_sec": 1
  },
  {
    "target": "chassis",
    "action": "MOVE",
    "params": {"x": 0.3, "y": 0, "z": 0, "speed": 0.3},
    "delay_sec": 3
  },
  {
    "target": "chassis",
    "action": "MOVE",
    "params": {"x": -0.3, "y": 0, "z": 0, "speed": 0.3},
    "delay_sec": 3
  },
  {
    "target": "led",
    "action": "SET",
    "params": {"r": 0, "g": 0, "b": 0, "eff": "off"},
    "delay_sec": 0
  }
]
EOF
)

  local payload
  payload=$(cat <<EOF
{
  "mission_name": "$mission_name",
  "target_stations": [],
  "conditions": {
    "robot_type":    "$robot_type",
    "robot_online":  true,
    "min_battery":   $min_battery,
    "max_latency_ms": 9999
  },
  "nodes": $nodes
}
EOF
)

  info "[$label] 미션 브로드캐스트 (robot_type=$robot_type min_battery=$min_battery)"
  local response
  response=$(curl -s -X POST "$HUB_URL/broadcast-mission" \
    -H "Content-Type: application/json" \
    -d "$payload" --max-time 10 \
    || echo '{"status":"error","message":"curl failed"}')

  local mission_id
  mission_id=$(echo "$response" | python3 -c \
    "import sys,json; print(json.load(sys.stdin).get('mission_id','ERROR'))" 2>/dev/null || echo "ERROR")

  echo "$mission_id"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST A: robot_type=ep01 → accept + 로봇 동작
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "TEST A — robot_type=ep01 (accept 예상 + 로봇 동작)"

MID_A=$(broadcast_mission "A-ep01" "$ROBOT_TYPE_CFG" 0)
ok "TEST A 미션 ID: $MID_A"

info "${WAIT_SEC}초 대기 (브로드캐스트 → accept → 로봇 명령 전달)..."
sleep "$WAIT_SEC"

# accept 확인
if grep -q "accept" "$LOG_DIR/mqtt_all.log" 2>/dev/null; then
  ok "TEST A [OK] accept 수신"
  grep "fleet/mission/accept" "$LOG_DIR/mqtt_all.log" | tail -3
else
  warn "TEST A [WARN] accept 미수신 — listener 로그 확인:"
  kubectl logs -n "$NAMESPACE" -l app=mission-listener --tail=20 2>/dev/null || true
fi

# Redis 명령 전달 확인
ROBOT_POD=$(kubectl get pod -n "$NAMESPACE" -l app=mission-listener \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$ROBOT_POD" ]]; then
  info "listener 로그 (TEST A):"
  kubectl logs -n "$NAMESPACE" "$ROBOT_POD" --tail=30 2>/dev/null || true
fi

# Redis cmd key 확인 (link_proxy가 소비했으면 비어있음)
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$REDIS_POD" ]]; then
  QLEN=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
    redis-cli llen "robot:$(cfg runtime.default_robot_sn):commands" 2>/dev/null || echo "N/A")
  info "Redis cmd queue 길이: $QLEN (0=link_proxy가 소비 중 또는 완료)"

  info "Redis 로봇 상태 (link_proxy 갱신값):"
  kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
    redis-cli hgetall "robot:$(cfg runtime.default_robot_sn):status" 2>/dev/null || true
fi

echo ""
info "로봇이 실제로 움직이는지 육안으로 확인하세요 ↑"
read -r -p "  TEST A 결과 (y=성공/n=실패): " A_RESULT

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST B: robot_type=go1 → reject 예상
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "TEST B — robot_type=go1 (reject 예상)"

MID_B=$(broadcast_mission "B-go1" "go1" 0)
ok "TEST B 미션 ID: $MID_B"

info "${WAIT_SEC}초 대기..."
sleep "$WAIT_SEC"

REJECT_COUNT=$(grep -c "reject" "$LOG_DIR/mqtt_all.log" 2>/dev/null || echo "0")
if [[ "$REJECT_COUNT" -gt 0 ]]; then
  ok "TEST B [OK] reject 수신 ($REJECT_COUNT 건)"
else
  warn "TEST B [WARN] reject 미수신 — 로봇 타입 조건 미작동 가능"
fi
grep "fleet/mission/accept" "$LOG_DIR/mqtt_all.log" | grep "go1\|reject" | tail -3 || true

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEST C: min_battery=999 → reject 예상
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "TEST C — min_battery=999 (reject 예상)"

MID_C=$(broadcast_mission "C-battery" "$ROBOT_TYPE_CFG" 999)
ok "TEST C 미션 ID: $MID_C"

info "${WAIT_SEC}초 대기..."
sleep "$WAIT_SEC"

REJECT2=$(grep -c "reject" "$LOG_DIR/mqtt_all.log" 2>/dev/null || echo "0")
if [[ "$REJECT2" -gt "$REJECT_COUNT" ]]; then
  ok "TEST C [OK] reject 수신 (배터리 조건 작동)"
else
  warn "TEST C [WARN] 추가 reject 없음"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 결과 요약
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "테스트 결과 요약"

kill "$MQTT_PID" 2>/dev/null || true

ACCEPT_CNT=$(grep -c "\"decision\": \"accept\"\|decision.*accept" "$LOG_DIR/mqtt_all.log" 2>/dev/null || echo "0")
REJECT_CNT=$(grep -c "\"decision\": \"reject\"\|decision.*reject" "$LOG_DIR/mqtt_all.log" 2>/dev/null || echo "0")

echo ""
echo -e "${BOLD}━━━ 최종 집계 ━━━${RESET}"
echo "  accept 수신: ${ACCEPT_CNT}건"
echo "  reject 수신: ${REJECT_CNT}건"
echo ""
echo "  TEST A (ep01 accept): $([ "$A_RESULT" = "y" ] && echo "[OK] PASS" || echo "[FAIL] FAIL")"
echo "  TEST B (go1 reject):  $([ "$REJECT_COUNT" -gt 0 ] && echo "[OK] PASS" || echo "[FAIL] FAIL")"
echo "  TEST C (battery):     $([ "$REJECT2" -gt "$REJECT_COUNT" ] && echo "[OK] PASS" || echo "[FAIL] FAIL")"
echo ""
echo "  전체 MQTT 로그: $LOG_DIR/mqtt_all.log"
echo "  listener 로그:  bash scripts/08_logs.sh robot"
echo "  link_proxy 로그 확인:"
echo "    kubectl logs -n $NAMESPACE -l app=ep01-link --tail=50"
