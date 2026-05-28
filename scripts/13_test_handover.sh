#!/usr/bin/env bash
# 13_test_handover.sh — Phase 2 핸드오버 E2E 테스트
#
# 테스트 순서:
#   1. RSSI Collector가 Redis에 값을 쓰고 있는지 확인
#   2. 미션 배포 (로봇이 계속 움직이는 미션)
#   3. Redis에 강제로 핸드오버 조건 주입 (B 기지국 RSSI를 높게 설정)
#   4. Handover Controller가 Prewarm + Handover 토픽을 발행하는지 확인
#   5. 새 기지국 broadcaster가 resume_from으로 재브로드캐스트하는지 확인
#   6. 미션이 끊기지 않고 계속되는지 확인
set -euo pipefail
source "$(dirname "$0")/common.sh"

HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
  -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "localhost")
HUB_URL="http://${HUB_NODE}:${HUB_PORT}"
ROBOT_SN="$(cfg runtime.default_robot_sn)"
STATION_A="station-a"
STATION_B="station-b"

LOG_DIR="/tmp/handover-test-$(date +%s)"
mkdir -p "$LOG_DIR"

section "Phase 2 핸드오버 E2E 테스트"
info "Hub: $HUB_URL"
info "MQTT: ${MQTT_HOST}:${MQTT_PORT}"
info "Robot SN: $ROBOT_SN"
info "Log: $LOG_DIR"

# ── MQTT 구독 시작 ────────────────────────────────────────────────
section "STEP 1 — MQTT 구독 시작"
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/#" -v \
  > "$LOG_DIR/mqtt.log" 2>&1 &
MQTT_PID=$!
sleep 1
ok "MQTT 구독 PID: $MQTT_PID"

# ── RSSI Collector 확인 ───────────────────────────────────────────
section "STEP 2 — RSSI Collector 확인"
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")

info "RSSI 키 목록 (rssi:*):"
kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli keys "rssi:*" 2>/dev/null || warn "RSSI 키 없음 — rssi_collector 실행 확인"

# ── 미션 배포 (반복 이동 — 핸드오버 중에도 계속 실행) ─────────────
section "STEP 3 — 핸드오버 테스트용 미션 배포"

MISSION_PAYLOAD=$(python3 - <<PYEOF
import json
payload = {
    "mission_name": "handover-test",
    "target_stations": [],
    "conditions": {"robot_type": "$(cfg robot.type)", "robot_online": True, "min_battery": 0},
    "nodes": [
        {"target": "flow", "action": "REPEAT", "params": {"times": 10},
         "body": [
             {"target": "chassis", "action": "MOVE",
              "params": {"x": 0.5, "y": 0, "speed": 0.3}, "delay_sec": 4},
             {"target": "chassis", "action": "MOVE",
              "params": {"x": -0.5, "y": 0, "speed": 0.3}, "delay_sec": 4},
         ], "delay_sec": 0}
    ]
}
print(json.dumps(payload))
PYEOF
)

RESPONSE=$(curl -s -X POST "$HUB_URL/broadcast-mission" \
  -H "Content-Type: application/json" \
  -d "$MISSION_PAYLOAD" --max-time 10 \
  || echo '{"status":"error"}')

MISSION_ID=$(echo "$RESPONSE" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('mission_id','ERROR'))" 2>/dev/null || echo "ERROR")
ok "미션 배포: $MISSION_ID"

info "10초 대기 (미션 실행 시작)..."
sleep 10

# ── 핸드오버 강제 트리거 ──────────────────────────────────────────
section "STEP 4 — 핸드오버 강제 트리거 (Redis RSSI 조작)"
info "station-a RSSI를 낮게, station-b RSSI를 높게 설정..."

# station-a: 약한 신호
kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli set \
  "rssi:${STATION_A}:${ROBOT_SN}" \
  '{"rssi":-80,"ewma":-80,"ssid":"RMEP-test","station":"station-a","sn":"'"$ROBOT_SN"'","ts":'"$(date +%s)"'}' \
  EX 30 > /dev/null

# station-b: 강한 신호 (threshold 10dB 초과)
kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli set \
  "rssi:${STATION_B}:${ROBOT_SN}" \
  '{"rssi":-60,"ewma":-60,"ssid":"RMEP-test","station":"station-b","sn":"'"$ROBOT_SN"'","ts":'"$(date +%s)"'}' \
  EX 30 > /dev/null

ok "RSSI 조작 완료 — station-a=-80dBm, station-b=-60dBm (차이=20dB > threshold=10dB)"
info "stable_count × scan_interval 만큼 대기..."

STABLE=$(cfg services.handover.stable_count 2>/dev/null || echo 3)
INTERVAL=$(cfg services.rssi.scan_interval_sec 2>/dev/null || echo 3)
WAIT=$(python3 -c "print(int($STABLE * $INTERVAL) + 5)")
info "  대기: ${WAIT}초 (stable=${STABLE} × interval=${INTERVAL}s + 5s 여유)"

for i in $(seq "$WAIT" -1 1); do
  printf "\r  남은 대기: %2ds" "$i"
  sleep 1
done
echo ""

# ── 핸드오버 이벤트 확인 ──────────────────────────────────────────
section "STEP 5 — 핸드오버 이벤트 확인"

if grep -q "fleet/handover/prewarm" "$LOG_DIR/mqtt.log" 2>/dev/null; then
  ok "Prewarm 토픽 수신"
  grep "fleet/handover/prewarm" "$LOG_DIR/mqtt.log" | tail -2
else
  warn "Prewarm 미수신 — handover_controller 로그 확인:"
  kubectl logs -n "$NAMESPACE" -l app=handover-controller --tail=20 2>/dev/null || true
fi

if grep -q "fleet/handover/$ROBOT_SN" "$LOG_DIR/mqtt.log" 2>/dev/null; then
  ok "Handover 토픽 수신"
  grep "fleet/handover/$ROBOT_SN" "$LOG_DIR/mqtt.log" | tail -2
else
  warn "Handover 토픽 미수신"
fi

if grep -q "resume_from" "$LOG_DIR/mqtt.log" 2>/dev/null; then
  ok "브로드캐스트 재개 (resume_from 포함)"
  grep "resume_from" "$LOG_DIR/mqtt.log" | tail -2
else
  info "resume_from 미수신 (broadcaster 재배포 없거나 미션 이미 완료)"
fi

# ── Redis 핸드오버 이벤트 확인 ────────────────────────────────────
section "STEP 6 — Redis 핸드오버 이벤트"
HO_RAW=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli get "handover:$ROBOT_SN" 2>/dev/null || echo "")
if [[ -n "$HO_RAW" ]]; then
  ok "Redis handover 키 존재:"
  echo "$HO_RAW" | python3 -m json.tool 2>/dev/null || echo "$HO_RAW"
else
  warn "Redis handover 키 없음 — 핸드오버 미발생"
fi

# ── 요약 ─────────────────────────────────────────────────────────
section "결과 요약"
kill "$MQTT_PID" 2>/dev/null || true

echo ""
echo -e "${BOLD}━━━ Phase 2 핸드오버 테스트 결과 ━━━${RESET}"
grep -q "fleet/handover/prewarm" "$LOG_DIR/mqtt.log" 2>/dev/null \
  && echo "  ✅ Prewarm 발행" || echo "  ❌ Prewarm 미발행"
grep -q "fleet/handover/$ROBOT_SN" "$LOG_DIR/mqtt.log" 2>/dev/null \
  && echo "  ✅ Handover 발행" || echo "  ❌ Handover 미발행"
grep -q "resume_from" "$LOG_DIR/mqtt.log" 2>/dev/null \
  && echo "  ✅ 미션 재개 브로드캐스트" || echo "  ⚠️  미션 재개 확인 필요"
[[ -n "$HO_RAW" ]] \
  && echo "  ✅ Redis 핸드오버 기록" || echo "  ❌ Redis 핸드오버 기록 없음"
echo ""
echo "  전체 MQTT 로그: $LOG_DIR/mqtt.log"
echo "  handover_controller 로그:"
echo "    kubectl logs -n $NAMESPACE -l app=handover-controller --tail=50"
