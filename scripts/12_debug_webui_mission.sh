#!/usr/bin/env bash
# 12_debug_webui_mission.sh — WebUI 미션 배포 후 전 구간 로그 실시간 출력
#
# 동작:
#   1. 모든 관련 서비스 로그를 백그라운드에서 캡처
#   2. WebUI와 동일한 payload로 Hub API 직접 호출 (WebUI 경로 재현)
#   3. 각 단계별 통과 여부를 실시간으로 체크
#   4. 문제 발생 지점 정확히 출력
#   5. 전체 로그를 파일로 저장
#
# 사용법:
#   bash scripts/12_debug_webui_mission.sh
#   ROBOT_TYPE=ep01 bash scripts/12_debug_webui_mission.sh   # 로봇 타입 오버라이드
#   VERBOSE=1 bash scripts/12_debug_webui_mission.sh          # 상세 로그
set -euo pipefail
source "$(dirname "$0")/common.sh"

# ── 설정 ────────────────────────────────────────────────────────
HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
  -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "localhost")
HUB_URL="http://${HUB_NODE}:${HUB_PORT}"
ROBOT_SN="$(cfg runtime.default_robot_sn)"
ROBOT_TYPE="${ROBOT_TYPE:-$(cfg robot.type)}"
VERBOSE="${VERBOSE:-0}"

LOG_DIR="/tmp/debug-webui-$(date +%s)"
mkdir -p "$LOG_DIR"

# 로그 파일 경로
LOG_MQTT="$LOG_DIR/mqtt_all.log"
LOG_HUB="$LOG_DIR/hub.log"
LOG_LISTENER="$LOG_DIR/listener.log"
LOG_LINK="$LOG_DIR/link_proxy.log"
LOG_BROADCASTER="$LOG_DIR/broadcaster.log"
LOG_SUMMARY="$LOG_DIR/summary.txt"

PIDS=()

cleanup() {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

# ══════════════════════════════════════════════════════════════════
section "환경 정보"
# ══════════════════════════════════════════════════════════════════
info "Hub URL:     $HUB_URL"
info "MQTT:        ${MQTT_HOST}:${MQTT_PORT}"
info "Robot SN:    $ROBOT_SN"
info "Robot Type:  $ROBOT_TYPE"
info "Namespace:   $NAMESPACE"
info "로그 디렉토리: $LOG_DIR"

# ══════════════════════════════════════════════════════════════════
section "STEP 0 — 사전 상태 스냅샷"
# ══════════════════════════════════════════════════════════════════

# Hub 헬스체크
info "Hub 헬스체크..."
HEALTH=$(curl -s --max-time 4 "$HUB_URL/health/k8s" 2>/dev/null || echo "{}")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

K3S_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('k3s_available',False))" 2>/dev/null || echo "false")
MQTT_OK=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mqtt_available',False))" 2>/dev/null || echo "false")

[[ "$K3S_OK" == "True" ]]  && ok "k3s 연결" || warn "k3s 미연결 (dry-run 모드)"
[[ "$MQTT_OK" == "True" ]] && ok "MQTT 연결" || err "MQTT 미연결 — Hub가 MQTT 브로커에 연결되지 않음"

# Redis Pod 확인
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -z "$REDIS_POD" ]]; then
  err "Redis Pod 없음"
  exit 1
fi
ok "Redis Pod: $REDIS_POD"

# 현재 Redis 로봇 상태 스냅샷
info "── 현재 Redis 로봇 상태 ──"
ROBOT_STATUS=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli hgetall "robot:${ROBOT_SN}:status" 2>/dev/null || echo "")
if [[ -n "$ROBOT_STATUS" ]]; then
  ok "robot:${ROBOT_SN}:status 존재 (link_proxy 연결됨)"
  echo "$ROBOT_STATUS"
else
  warn "robot:${ROBOT_SN}:status 없음 — link_proxy가 아직 연결 안 됨"
  warn "listener는 환경변수 폴백값으로 조건 판단합니다"
fi

# 현재 cmd queue 길이
CMD_QLEN=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli llen "robot:${ROBOT_SN}:commands" 2>/dev/null || echo "?")
info "현재 cmd queue 길이: $CMD_QLEN"
if [[ "$CMD_QLEN" != "0" && "$CMD_QLEN" != "?" ]]; then
  warn "큐에 이전 명령이 남아있음 — 플러시 여부 선택"
  read -r -p "  기존 cmd queue를 비울까요? (y/n): " FLUSH
  if [[ "$FLUSH" == "y" ]]; then
    kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- redis-cli del "robot:${ROBOT_SN}:commands"
    ok "cmd queue 초기화"
  fi
fi

# Pod 전체 상태
info "── Pod 상태 ──"
kubectl get pods -n "$NAMESPACE" -o wide

# ══════════════════════════════════════════════════════════════════
section "STEP 1 — 로그 스트림 시작 (백그라운드)"
# ══════════════════════════════════════════════════════════════════

# MQTT 전체 구독
mosquitto_sub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/#" -v \
  > "$LOG_MQTT" 2>&1 &
PIDS+=($!)
info "MQTT 구독 시작 (PID ${PIDS[-1]}) → $LOG_MQTT"

# Hub 로그
kubectl logs -n "$NAMESPACE" -l app=central-hub -f --tail=0 \
  > "$LOG_HUB" 2>&1 &
PIDS+=($!)
info "Hub 로그 스트림 (PID ${PIDS[-1]}) → $LOG_HUB"

# listener 로그
LISTENER_POD=$(kubectl get pod -n "$NAMESPACE" -l app=mission-listener \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$LISTENER_POD" ]]; then
  kubectl logs -n "$NAMESPACE" "$LISTENER_POD" -f --tail=0 \
    > "$LOG_LISTENER" 2>&1 &
  PIDS+=($!)
  info "listener 로그 스트림 (PID ${PIDS[-1]}) → $LOG_LISTENER"
else
  warn "mission-listener Pod 없음 — 로그 스트림 생략"
fi

# link_proxy 로그
LINK_POD=$(kubectl get pod -n "$NAMESPACE" -l app=ep01-link \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$LINK_POD" ]]; then
  kubectl logs -n "$NAMESPACE" "$LINK_POD" -f --tail=0 \
    > "$LOG_LINK" 2>&1 &
  PIDS+=($!)
  info "link_proxy 로그 스트림 (PID ${PIDS[-1]}) → $LOG_LINK"
else
  warn "ep01-link Pod 없음 — link_proxy 로그 생략"
fi

# broadcaster 로그
BROADCASTER_POD=$(kubectl get pod -n "$NAMESPACE" -l app=edge-broadcaster \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$BROADCASTER_POD" ]]; then
  kubectl logs -n "$NAMESPACE" "$BROADCASTER_POD" -f --tail=0 \
    > "$LOG_BROADCASTER" 2>&1 &
  PIDS+=($!)
  info "broadcaster 로그 스트림 (PID ${PIDS[-1]}) → $LOG_BROADCASTER"
else
  warn "edge-broadcaster Pod 없음 — broadcaster 로그 생략"
fi

sleep 1
ok "모든 로그 스트림 준비 완료"

# ══════════════════════════════════════════════════════════════════
section "STEP 2 — WebUI와 동일한 payload로 Hub API 호출"
# ══════════════════════════════════════════════════════════════════

MISSION_NAME="debug-webui-$(date +%s)"

# WebUI 브로드캐스트 탭의 기본값과 동일하게 구성
# robot_online=true, min_battery=20 — 이게 WebUI 기본값
MISSION_PAYLOAD=$(python3 - <<PYEOF
import json

# WebUI render_broadcast_tab 의 기본값과 100% 동일
payload = {
    "mission_name":    "$MISSION_NAME",
    "target_stations": [],          # 전체 기지국 (WebUI 기본값)
    "conditions": {
        "robot_type":    "$ROBOT_TYPE",
        "robot_online":  True,      # WebUI 기본값 (체크됨)
        "min_battery":   20,        # WebUI 기본값
        "max_latency_ms": 9999,
    },
    "nodes": [
        {
            "target":    "chassis",
            "action":    "MOVE",
            "params":    {"x": 0.3, "y": 0, "z": 0, "speed": 0.3},
            "delay_sec": 3.0,
        },
        {
            "target":    "led",
            "action":    "SET",
            "params":    {"r": 255, "g": 0, "b": 0, "eff": "on"},
            "delay_sec": 1.0,
        },
    ],
}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PYEOF
)

info "전송 payload:"
echo "$MISSION_PAYLOAD" | python3 -m json.tool

RESPONSE=$(curl -s -X POST "$HUB_URL/broadcast-mission" \
  -H "Content-Type: application/json" \
  -d "$MISSION_PAYLOAD" \
  --max-time 10 \
  || echo '{"status":"error","message":"curl failed"}')

info "Hub 응답:"
echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

MISSION_ID=$(echo "$RESPONSE" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('mission_id','ERROR'))" 2>/dev/null || echo "ERROR")
MQTT_SENT=$(echo "$RESPONSE" | python3 -c \
  "import sys,json; print(json.load(sys.stdin).get('mqtt_sent',False))" 2>/dev/null || echo "false")

if [[ "$MISSION_ID" == "ERROR" ]]; then
  err "Hub API 호출 실패 — Hub 로그 확인"
  echo "--- Hub 로그 ---"
  cat "$LOG_HUB" 2>/dev/null || true
  exit 1
fi
ok "미션 ID: $MISSION_ID"

# ══════════════════════════════════════════════════════════════════
section "STEP 3 — MQTT 발행 확인"
# ══════════════════════════════════════════════════════════════════

if [[ "$MQTT_SENT" == "True" ]] || [[ "$MQTT_SENT" == "true" ]]; then
  ok "Hub → MQTT fleet/mission/deploy 발행 성공"
else
  err "MQTT 발행 실패"
  err "원인 후보:"
  err "  1. Hub의 MQTT 클라이언트가 브로커에 연결 안 됨"
  err "  2. config.yaml mqtt.host가 틀림 (현재: $MQTT_HOST)"
  echo ""
  info "Hub 로그 (최근 20줄):"
  cat "$LOG_HUB" 2>/dev/null | tail -20 || true
  echo ""
  info "MQTT 브로커 직접 테스트:"
  mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/ping" -m "test" 2>&1 \
    && ok "브로커 접근 가능" || err "브로커 접근 불가 — mosquitto 실행 여부 확인"
fi

# ══════════════════════════════════════════════════════════════════
section "STEP 4 — broadcaster 수신 확인 (3초 대기)"
# ══════════════════════════════════════════════════════════════════
sleep 3

info "── broadcaster 로그 ──"
cat "$LOG_BROADCASTER" 2>/dev/null | grep -E "Broadcasted|deploy|ERROR|error|warn" || true

if grep -q "fleet/mission/broadcast" "$LOG_MQTT" 2>/dev/null; then
  ok "broadcaster → fleet/mission/broadcast 발행 확인"
  grep "fleet/mission/broadcast" "$LOG_MQTT" | tail -2
else
  err "fleet/mission/broadcast 미수신"
  err "원인 후보:"
  err "  1. broadcaster Pod가 fleet/mission/deploy 를 구독 안 함"
  err "  2. broadcaster Pod가 실행 중이 아님"
  err "  3. STATION_ID 필터 (target_stations)가 일치하지 않음"
  echo ""
  info "broadcaster 전체 로그:"
  cat "$LOG_BROADCASTER" 2>/dev/null || warn "  로그 없음"
fi

# ══════════════════════════════════════════════════════════════════
section "STEP 5 — listener 수신 + 조건 판단 확인 (5초 대기)"
# ══════════════════════════════════════════════════════════════════
sleep 5

info "── listener 로그 ──"
cat "$LOG_LISTENER" 2>/dev/null | tail -30 || warn "listener 로그 없음"

# accept/reject 여부
ACCEPT_LINE=$(grep -E "ACCEPT|REJECT|accept|reject" "$LOG_LISTENER" 2>/dev/null | tail -3 || echo "")
MQTT_ACCEPT=$(grep "fleet/mission/accept" "$LOG_MQTT" 2>/dev/null | tail -1 || echo "")

if [[ -n "$ACCEPT_LINE" ]]; then
  info "listener 판단 결과:"
  echo "  $ACCEPT_LINE"

  if echo "$ACCEPT_LINE" | grep -qi "ACCEPT"; then
    ok "listener → ACCEPT"
  else
    err "listener → REJECT"
    echo ""
    err "── 조건 불일치 분석 ──"

    # Redis 상태 vs 조건 비교
    BATT_RAW=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
      redis-cli hget "robot:${ROBOT_SN}:status" battery 2>/dev/null || echo "")
    if [[ -n "$BATT_RAW" ]]; then
      BATT_SOC=$(echo "$BATT_RAW" | python3 -c "import sys,json; print(json.load(sys.stdin).get('soc','?'))" 2>/dev/null || echo "?")
      info "  Redis 배터리: ${BATT_SOC}%  (조건: min_battery=20)"
      if [[ "$BATT_SOC" != "?" ]] && (( $(echo "$BATT_SOC < 20" | bc -l 2>/dev/null || echo 0) )); then
        err "  → 배터리 부족으로 REJECT"
      fi
    else
      warn "  Redis 배터리 정보 없음 — listener 환경변수 폴백 사용"
      warn "  ROBOT_ONLINE 환경변수값 확인 필요:"
      kubectl exec -n "$NAMESPACE" "$LISTENER_POD" -- \
        env 2>/dev/null | grep -E "ROBOT|BATTERY" || true
    fi

    info "  listener 환경변수:"
    kubectl exec -n "$NAMESPACE" "${LISTENER_POD:-none}" -- \
      env 2>/dev/null | grep -E "ROBOT_TYPE|ROBOT_ONLINE|BATTERY" | sort || true
    info "  미션 조건:"
    echo "    robot_type=$ROBOT_TYPE  robot_online=true  min_battery=20"
  fi
elif [[ -n "$MQTT_ACCEPT" ]]; then
  ok "MQTT accept 토픽 수신:"
  echo "  $MQTT_ACCEPT"
else
  err "listener가 브로드캐스트를 수신하지 못했거나 로그가 없음"
  err "원인 후보:"
  err "  1. listener Pod가 fleet/mission/broadcast 구독 안 함"
  err "  2. listener Pod가 실행 안 됨"
  err "  3. MQTT 브로커 접근 불가"
  echo ""
  info "listener Pod 상태:"
  kubectl get pod -n "$NAMESPACE" -l app=mission-listener 2>/dev/null || true
fi

# ══════════════════════════════════════════════════════════════════
section "STEP 6 — Redis cmd queue 확인"
# ══════════════════════════════════════════════════════════════════

sleep 2
NEW_QLEN=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli llen "robot:${ROBOT_SN}:commands" 2>/dev/null || echo "?")
info "cmd queue 현재 길이: $NEW_QLEN"

if [[ "$NEW_QLEN" != "0" && "$NEW_QLEN" != "?" && "$NEW_QLEN" -gt 0 ]]; then
  ok "Redis cmd queue에 명령이 쌓임 — listener → Redis LPUSH 성공"
  info "대기 중인 명령:"
  kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
    redis-cli lrange "robot:${ROBOT_SN}:commands" 0 -1 2>/dev/null | \
    while read -r line; do
      echo "  $line" | python3 -m json.tool 2>/dev/null || echo "  $line"
    done
else
  # 0이면 link_proxy가 이미 소비했거나 LPUSH 자체가 안 된 것
  if echo "$ACCEPT_LINE" | grep -qi "ACCEPT" 2>/dev/null; then
    info "큐 비어있음 — link_proxy가 이미 소비했을 수 있음"
    info "link_proxy 로그 확인:"
    cat "$LOG_LINK" 2>/dev/null | tail -20 || warn "  link_proxy 로그 없음"
  else
    err "REJECT 상태에서 큐도 비어있음 — 명령 전달 안 됨 (정상)"
  fi
fi

# ══════════════════════════════════════════════════════════════════
section "STEP 7 — link_proxy 실행 확인 (5초 대기)"
# ══════════════════════════════════════════════════════════════════
sleep 5

info "── link_proxy 로그 ──"
cat "$LOG_LINK" 2>/dev/null | tail -30 || warn "link_proxy 로그 없음 (Pod 없거나 미연결)"

# 명령 실행 여부
if grep -qi "실행\|MOVE\|완료\|✅\|execute\|LPUSH" "$LOG_LINK" 2>/dev/null; then
  ok "link_proxy가 명령을 수신/실행한 로그 있음"
elif [[ -n "$LINK_POD" ]]; then
  warn "link_proxy 로그에 명령 실행 흔적 없음"
  warn "원인 후보:"
  warn "  1. BLPOP timeout — Redis cmd 키가 link_proxy 실행 전에 없었음"
  warn "  2. 로봇 연결 실패 (ROBOT_IP 환경변수 확인)"
  info "link_proxy 환경변수:"
  kubectl exec -n "$NAMESPACE" "$LINK_POD" -- \
    env 2>/dev/null | grep -E "ROBOT|REDIS" | sort || true
fi

# ══════════════════════════════════════════════════════════════════
section "STEP 8 — 체크포인트 + accept 결과 확인"
# ══════════════════════════════════════════════════════════════════

info "Redis 체크포인트:"
CP=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
  redis-cli get "fleet:cache:${ROBOT_SN}" 2>/dev/null || echo "")
if [[ -n "$CP" ]]; then
  ok "체크포인트 존재:"
  echo "$CP" | python3 -m json.tool 2>/dev/null || echo "$CP"
else
  info "체크포인트 없음 (미션 미실행 또는 완료)"
fi

info "Hub accept 결과 조회:"
curl -s "$HUB_URL/mission-results/$MISSION_ID" --max-time 5 | \
  python3 -m json.tool 2>/dev/null || true

info "MQTT accept 전체:"
grep "fleet/mission/accept\|fleet/mission/accepted" "$LOG_MQTT" 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════
section "요약 및 진단"
# ══════════════════════════════════════════════════════════════════

{
echo "════════════════════════════════════════════════════════"
echo "디버그 요약: $MISSION_ID"
echo "════════════════════════════════════════════════════════"
echo "실행시각:   $(date)"
echo "Hub URL:    $HUB_URL"
echo "MQTT:       ${MQTT_HOST}:${MQTT_PORT}"
echo "Robot SN:   $ROBOT_SN"
echo "Robot Type: $ROBOT_TYPE"
echo ""
echo "[체크리스트]"
[[ "$MQTT_SENT" == "True" || "$MQTT_SENT" == "true" ]] \
  && echo "  ✅ Hub MQTT 발행" || echo "  ❌ Hub MQTT 발행 실패"
grep -q "fleet/mission/broadcast" "$LOG_MQTT" 2>/dev/null \
  && echo "  ✅ broadcaster 발행" || echo "  ❌ broadcaster 발행 실패"
echo "$ACCEPT_LINE" | grep -qi "ACCEPT" 2>/dev/null \
  && echo "  ✅ listener ACCEPT" || echo "  ❌ listener REJECT/미수신"
[[ "$NEW_QLEN" != "0" && "$NEW_QLEN" != "?" ]] || \
grep -qi "실행\|MOVE\|완료\|✅" "$LOG_LINK" 2>/dev/null \
  && echo "  ✅ Redis cmd 전달" || echo "  ❌ Redis cmd 미전달"
grep -qi "실행\|MOVE\|완료\|✅" "$LOG_LINK" 2>/dev/null \
  && echo "  ✅ link_proxy 실행" || echo "  ❌ link_proxy 미실행"
echo ""
echo "[로그 파일]"
echo "  MQTT:        $LOG_MQTT"
echo "  Hub:         $LOG_HUB"
echo "  listener:    $LOG_LISTENER"
echo "  link_proxy:  $LOG_LINK"
echo "  broadcaster: $LOG_BROADCASTER"
} | tee "$LOG_SUMMARY"

echo ""
info "전체 요약 저장: $LOG_SUMMARY"
echo ""

# 어느 단계에서 막혔는지 최종 판단
if ! { [[ "$MQTT_SENT" == "True" ]] || [[ "$MQTT_SENT" == "true" ]]; }; then
  echo -e "${RED}${BOLD}▶ 막힌 지점: Hub → MQTT 브로커 연결 문제${RESET}"
  echo "  확인: kubectl logs -n $NAMESPACE -l app=central-hub | grep -i mqtt"
elif ! grep -q "fleet/mission/broadcast" "$LOG_MQTT" 2>/dev/null; then
  echo -e "${RED}${BOLD}▶ 막힌 지점: broadcaster가 deploy 토픽 미수신 또는 필터링${RESET}"
  echo "  확인: cat $LOG_BROADCASTER"
elif echo "$ACCEPT_LINE" | grep -qi "REJECT" 2>/dev/null; then
  echo -e "${RED}${BOLD}▶ 막힌 지점: listener가 조건 불일치로 REJECT${RESET}"
  echo "  확인: cat $LOG_LISTENER"
  echo "  힌트: robot_online=true 인데 Redis에 로봇 상태 없으면 reject"
  echo "        → link_proxy 먼저 실행 후 다시 시도"
elif [[ "$NEW_QLEN" == "0" ]] && ! grep -qi "ACCEPT" "$LOG_LISTENER" 2>/dev/null; then
  echo -e "${RED}${BOLD}▶ 막힌 지점: listener가 브로드캐스트 미수신${RESET}"
  echo "  확인: kubectl logs -n $NAMESPACE -l app=mission-listener"
elif ! grep -qi "실행\|MOVE\|완료\|✅" "$LOG_LINK" 2>/dev/null; then
  echo -e "${RED}${BOLD}▶ 막힌 지점: link_proxy가 Redis cmd 미수신 또는 로봇 미연결${RESET}"
  echo "  확인: cat $LOG_LINK"
  echo "  힌트: ROBOT_IP 환경변수, 로봇 AP 연결 여부 확인"
else
  echo -e "${GREEN}${BOLD}▶ 파이프라인 정상 — 로봇 육안 동작 여부 확인${RESET}"
fi

echo ""
info "전체 MQTT 실시간 보기:  tail -f $LOG_MQTT"
info "listener 실시간 보기:   tail -f $LOG_LISTENER"
info "link_proxy 실시간 보기: tail -f $LOG_LINK"
