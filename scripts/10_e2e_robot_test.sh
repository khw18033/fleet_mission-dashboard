#!/usr/bin/env bash
# 10_e2e_robot_test.sh — EP01 실제 동작 E2E 테스트
#
# 미션 순서:
#   1. 전진 0.5m  (chassis MOVE x=0.5)
#   2. 그리퍼 닫기 (actuator GRIPPER grip=50)
#   3. 빨간 LED   (led SET r=255 g=0 b=0)
#
# 사전 조건:
#   - link_proxy Pod 가 robot 노드에서 실행 중 (로봇 AP 연결 완료)
#   - mission-listener Pod 가 robot 노드에서 실행 중
#   - edge-broadcaster Pod 가 edge 노드에서 실행 중
#   - MQTT 브로커 접근 가능
set -euo pipefail
source "$(dirname "$0")/common.sh"

# ── 설정 ────────────────────────────────────────────────────────
HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
  -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "localhost")
HUB_NODE_PORT="$(cfg kubernetes.node_port)"
HUB_URL="http://${HUB_NODE}:${HUB_NODE_PORT}"
ROBOT_SN="$(cfg runtime.default_robot_sn)"
ROBOT_TYPE="$(cfg robot.type)"

# 각 노드별 동작 완료 여유 시간 (초)
# chassis MOVE는 wait_for_completed() 사용 → delay_sec = 이동 예상 시간 + 여유
MOVE_DELAY=5      # 0.5m / 0.3m/s ≈ 1.7초 + 여유
GRIPPER_DELAY=3   # gripper + time.sleep(1) + 여유
LED_DELAY=1       # LED는 즉시 완료

LOG_DIR="/tmp/e2e-$(date +%s)"
mkdir -p "$LOG_DIR"

section "E2E 테스트 시작"
info "Hub:        $HUB_URL"
info "MQTT:       ${MQTT_HOST}:${MQTT_PORT}"
info "Robot SN:   $ROBOT_SN"
info "Robot Type: $ROBOT_TYPE"
info "Log dir:    $LOG_DIR"

# ── 사전 상태 점검 ───────────────────────────────────────────────
section "사전 상태 점검"

# Hub 응답
HEALTH=$(curl -s --max-time 4 "$HUB_URL/health/k8s" || echo "{}")
MQTT_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mqtt_available',False))" 2>/dev/null || echo "false")
if [[ "$MQTT_OK" != "True" && "$MQTT_OK" != "true" ]]; then
  warn "Hub의 MQTT 연결이 확인되지 않음 — 계속 진행하지만 배포가 실패할 수 있습니다"
fi

# link_proxy Pod 확인
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "$REDIS_POD" ]]; then
  err "Redis Pod 없음 — 02_deploy_infra.sh 먼저 실행하세요"
  exit 1
fi

# Redis에 로봇 상태 키가 있는지 확인 (link_proxy 연결 여부)
STATUS=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli hgetall "robot:${ROBOT_SN}:status" 2>/dev/null || echo "")
if [[ -z "$STATUS" ]]; then
  warn "Redis에 robot:${ROBOT_SN}:status 없음"
  warn "link_proxy가 로봇에 연결되지 않았을 수 있습니다"
  warn "계속 진행합니다 — Redis cmd queue에 명령을 넣어두면 link_proxy 연결 시 즉시 실행됩니다"
else
  ok "로봇 상태 키 확인:"
  echo "$STATUS"
fi

# MQTT 구독 시작 (전체 fleet 토픽)
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/#" -v \
  > "$LOG_DIR/mqtt.log" 2>&1 &
MQTT_PID=$!
sleep 1
ok "MQTT 구독 시작 (PID $MQTT_PID)"

# ── 미션 페이로드 구성 ───────────────────────────────────────────
section "미션 페이로드 구성"

MISSION_NAME="e2e-robot-test-$(date +%s)"
MISSION_PAYLOAD=$(python3 - <<PYEOF
import json
payload = {
    "mission_name": "$MISSION_NAME",
    "target_stations": [],
    "conditions": {
        "robot_type":    "$ROBOT_TYPE",
        "robot_online":  True,
        "min_battery":   0,
        "max_latency_ms": 9999
    },
    "nodes": [
        {
            "target": "chassis",
            "action": "MOVE",
            "params": {"x": 0.5, "y": 0, "z": 0, "speed": 0.3},
            "delay_sec": $MOVE_DELAY
        },
        {
            "target": "actuator",
            "action": "GRIPPER",
            "params": {"grip": "close", "grip_p": 50},
            "delay_sec": $GRIPPER_DELAY
        },
        {
            "target": "led",
            "action": "SET",
            "params": {"r": 255, "g": 0, "b": 0, "eff": "on"},
            "delay_sec": $LED_DELAY
        }
    ]
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PYEOF
)

info "미션 내용:"
echo "$MISSION_PAYLOAD" | python3 -m json.tool

# ── STEP 1: 미션 배포 ────────────────────────────────────────────
section "STEP 1 — 미션 브로드캐스트 배포"

RESPONSE=$(curl -s -X POST "$HUB_URL/broadcast-mission" \
  -H "Content-Type: application/json" \
  -d "$MISSION_PAYLOAD" \
  --max-time 10 \
  || echo '{"status":"error","message":"curl failed"}')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

MISSION_ID=$(echo "$RESPONSE" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('mission_id','ERROR'))" 2>/dev/null || echo "ERROR")
MQTT_SENT=$(echo "$RESPONSE" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('mqtt_sent',False))" 2>/dev/null || echo "false")

if [[ "$MISSION_ID" == "ERROR" ]]; then
  err "미션 배포 실패"
  kill "$MQTT_PID" 2>/dev/null || true
  exit 1
fi
ok "미션 ID: $MISSION_ID"

if [[ "$MQTT_SENT" == "True" ]] || [[ "$MQTT_SENT" == "true" ]]; then
  ok "MQTT 발행 성공"
else
  warn "MQTT 발행 실패 — Hub MQTT 연결 상태 확인 필요"
fi

# ── STEP 2: 브로드캐스트 수신 확인 ──────────────────────────────
section "STEP 2 — 브로드캐스트 수신 확인 (3초 대기)"
sleep 3

if grep -q "fleet/mission/broadcast" "$LOG_DIR/mqtt.log" 2>/dev/null; then
  ok "broadcaster → fleet/mission/broadcast 발행 확인"
else
  warn "broadcast 토픽 미수신"
  info "broadcaster Pod 로그:"
  kubectl logs -n "$NAMESPACE" -l app=edge-broadcaster --tail=15 2>/dev/null || true
fi

# ── STEP 3: accept 확인 ──────────────────────────────────────────
section "STEP 3 — accept 수신 확인 (5초 대기)"
sleep 5

ACCEPT_LINE=$(grep "fleet/mission/accept" "$LOG_DIR/mqtt.log" 2>/dev/null | tail -1 || echo "")
if [[ -n "$ACCEPT_LINE" ]]; then
  ok "accept 수신:"
  echo "  $ACCEPT_LINE"
  DECISION=$(echo "$ACCEPT_LINE" | python3 -c \
    "import sys,json; line=sys.stdin.read(); \
     parts=line.strip().split(' ',1); \
     d=json.loads(parts[1]) if len(parts)>1 else {}; \
     print(d.get('decision','?'))" 2>/dev/null || echo "?")
  REASON=$(echo "$ACCEPT_LINE" | python3 -c \
    "import sys,json; line=sys.stdin.read(); \
     parts=line.strip().split(' ',1); \
     d=json.loads(parts[1]) if len(parts)>1 else {}; \
     print(d.get('reason',''))" 2>/dev/null || echo "")
  info "결정: $DECISION  이유: ${REASON:-ok}"
  if [[ "$DECISION" != "accept" ]]; then
    err "REJECT — 조건 불일치: $REASON"
    err "config.yaml의 robot.type(${ROBOT_TYPE})과 ROBOT_TYPE 환경변수가 일치하는지 확인하세요"
    kill "$MQTT_PID" 2>/dev/null || true
    exit 1
  fi
else
  err "accept 수신 없음 — listener Pod 로그 확인:"
  kubectl logs -n "$NAMESPACE" -l app=mission-listener --tail=30 2>/dev/null || true
  kill "$MQTT_PID" 2>/dev/null || true
  exit 1
fi

# ── STEP 4: Redis cmd queue 확인 ─────────────────────────────────
section "STEP 4 — Redis cmd queue 확인"

QLEN=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli llen "robot:${ROBOT_SN}:commands" 2>/dev/null || echo "N/A")
info "robot:${ROBOT_SN}:commands 큐 길이: $QLEN"
info "(link_proxy가 실행 중이면 즉시 소비, 0이면 이미 처리 중)"

# 큐에 남아있는 명령 미리보기 (소비 안 함 — LRANGE 사용)
PREVIEW=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli lrange "robot:${ROBOT_SN}:commands" 0 4 2>/dev/null || echo "")
if [[ -n "$PREVIEW" ]]; then
  info "대기 중인 명령 미리보기:"
  echo "$PREVIEW" | while read -r line; do
    echo "  $line" | python3 -m json.tool 2>/dev/null || echo "  $line"
  done
fi

# ── STEP 5: 로봇 동작 대기 ───────────────────────────────────────
TOTAL_MISSION_SEC=$(( MOVE_DELAY + GRIPPER_DELAY + LED_DELAY + 5 ))
section "STEP 5 — 로봇 동작 대기 (${TOTAL_MISSION_SEC}초)"
info "예상 동작 순서:"
info "  1. 전진 0.5m  (약 ${MOVE_DELAY}초)"
info "  2. 그리퍼 닫기 (약 ${GRIPPER_DELAY}초)"
info "  3. 빨간 LED 켜기"
echo ""
info "⚠️  로봇 앞 공간을 확보하세요 (0.5m 이상)"

# 카운트다운
for i in $(seq "$TOTAL_MISSION_SEC" -1 1); do
  printf "\r  남은 대기: %2ds  " "$i"
  sleep 1
done
echo ""

# ── STEP 6: 실행 결과 확인 ───────────────────────────────────────
section "STEP 6 — 실행 결과 확인"

# Redis 최신 로봇 상태
info "Redis 로봇 최종 상태:"
kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli hgetall "robot:${ROBOT_SN}:status" 2>/dev/null | \
  python3 -c "
import sys
lines = sys.stdin.read().strip().split('\n')
pairs = [(lines[i], lines[i+1]) for i in range(0, len(lines)-1, 2)]
import json
for k, v in pairs:
    try: print(f'  {k}: {json.dumps(json.loads(v), ensure_ascii=False)}')
    except: print(f'  {k}: {v}')
" 2>/dev/null || true

# 체크포인트 확인
info "체크포인트 (진행 기록):"
CACHE=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli get "fleet:cache:${ROBOT_SN}" 2>/dev/null || echo "")
if [[ -n "$CACHE" ]]; then
  echo "$CACHE" | python3 -m json.tool 2>/dev/null || echo "$CACHE"
fi

# 완료 체크포인트 MQTT 확인
if grep -q '"status": "completed"\|status.*completed' "$LOG_DIR/mqtt.log" 2>/dev/null; then
  ok "미션 완료 체크포인트 수신"
else
  info "완료 체크포인트 미수신 (아직 수행 중이거나 link_proxy 미연결)"
fi

# link_proxy 로그
info "link_proxy 로그 (최근 40줄):"
kubectl logs -n "$NAMESPACE" -l app=ep01-link --tail=40 2>/dev/null || \
  warn "  link_proxy Pod 없음 (라벨 확인 필요)"

# listener 로그
info "mission-listener 로그 (최근 20줄):"
kubectl logs -n "$NAMESPACE" -l app=mission-listener --tail=20 2>/dev/null || true

# Hub accept 결과 조회
info "Hub API accept 결과:"
curl -s "$HUB_URL/mission-results/$MISSION_ID" --max-time 5 | \
  python3 -m json.tool 2>/dev/null || true

# ── 최종 판정 ────────────────────────────────────────────────────
section "최종 판정"
kill "$MQTT_PID" 2>/dev/null || true

echo ""
echo -e "${BOLD}━━━ E2E 테스트 결과 ━━━${RESET}"
echo "  미션 ID:  $MISSION_ID"
echo "  미션 이름: $MISSION_NAME"
echo ""
echo "  파이프라인 체크:"
grep -q "fleet/mission/broadcast" "$LOG_DIR/mqtt.log" 2>/dev/null \
  && echo "  ✅ 브로드캐스트 발행" || echo "  ❌ 브로드캐스트 미발행"
grep -q "\"decision\": \"accept\"\|decision.*accept" "$LOG_DIR/mqtt.log" 2>/dev/null \
  && echo "  ✅ accept 수신" || echo "  ❌ accept 미수신"
[[ -z "$QLEN" || "$QLEN" == "0" || "$QLEN" == "N/A" ]] \
  && echo "  ✅ Redis cmd 소비됨 (link_proxy 처리)" \
  || echo "  ⚠️  Redis cmd 큐 잔여: $QLEN (link_proxy 연결 확인)"
echo ""
echo "  로봇 동작 확인 (육안):"
read -r -p "  1. 전진 0.5m 동작 여부 (y/n): " R1
read -r -p "  2. 그리퍼 닫힘 여부     (y/n): " R2
read -r -p "  3. 빨간 LED 켜짐 여부   (y/n): " R3
echo ""
echo "  결과:"
[[ "$R1" == "y" ]] && echo "  ✅ 전진" || echo "  ❌ 전진 실패"
[[ "$R2" == "y" ]] && echo "  ✅ 그리퍼" || echo "  ❌ 그리퍼 실패"
[[ "$R3" == "y" ]] && echo "  ✅ LED" || echo "  ❌ LED 실패"

ALL_PASS=true
[[ "$R1" != "y" || "$R2" != "y" || "$R3" != "y" ]] && ALL_PASS=false

echo ""
if $ALL_PASS; then
  echo -e "  ${GREEN}${BOLD}🎉 E2E 테스트 전체 통과${RESET}"
else
  echo -e "  ${RED}${BOLD}❌ 일부 항목 실패 — 아래 로그를 확인하세요${RESET}"
  echo "  MQTT 전체 로그:  $LOG_DIR/mqtt.log"
  echo "  listener 로그:   bash scripts/08_logs.sh robot"
  echo "  link_proxy 로그: kubectl logs -n $NAMESPACE -l app=ep01-link -f"
fi
