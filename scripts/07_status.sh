#!/usr/bin/env bash
# 07_status.sh — 전체 클러스터 및 서비스 상태
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "노드 상태"
kubectl get nodes -L node-role -o wide

section "전체 Pod ($NAMESPACE)"
kubectl get pods -n "$NAMESPACE" -o wide

section "DaemonSet 상태"
kubectl get daemonset -n "$NAMESPACE" 2>/dev/null || info "(없음)"

section "서비스"
kubectl get svc -n "$NAMESPACE"

section "ConfigMap"
kubectl get configmap -n "$NAMESPACE" | grep -E "fleet-config|robot-config" || info "(없음)"

section "central-hub 헬스체크"
HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
  -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "")
if [[ -n "$HUB_NODE" ]]; then
  info "Hub: http://${HUB_NODE}:${HUB_PORT}"
  curl -s --max-time 3 "http://${HUB_NODE}:${HUB_PORT}/health/k8s" \
    | python3 -m json.tool 2>/dev/null || warn "Hub 응답 없음"
else
  warn "central-hub Pod 없음"
fi

section "MQTT 브로커"
if mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -t "fleet/ping" -m "ok" 2>/dev/null; then
  ok "MQTT 응답 (${MQTT_HOST}:${MQTT_PORT})"
else
  warn "MQTT 응답 없음"
fi

section "Redis 키 현황"
REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
if [[ -n "$REDIS_POD" ]]; then
  for pattern in "robot:*:online" "rssi:*" "handover:*" "fleet:cache:*" "mission:*"; do
    COUNT=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
      redis-cli keys "$pattern" 2>/dev/null | wc -l | tr -d ' ')
    info "  $pattern → ${COUNT}개"
  done
else
  warn "Redis Pod 없음"
fi
