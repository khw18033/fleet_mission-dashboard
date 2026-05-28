#!/usr/bin/env bash
# 08_logs.sh — 서비스별 로그 확인
#
# 사용법:
#   bash scripts/08_logs.sh                # 전체
#   bash scripts/08_logs.sh hub            # central-hub
#   bash scripts/08_logs.sh edge           # broadcaster
#   bash scripts/08_logs.sh robot          # listener
#   bash scripts/08_logs.sh rssi           # rssi-collector
#   bash scripts/08_logs.sh handover       # handover-controller
#   bash scripts/08_logs.sh fallback       # fallback-controller
#   TAIL=100 bash scripts/08_logs.sh hub
set -euo pipefail
source "$(dirname "$0")/common.sh"

TARGET="${1:-all}"
TAIL="${TAIL:-30}"

show_logs() {
  local label="$1" selector="$2"
  section "$label 로그 (tail=$TAIL)"
  POD=$(kubectl get pod -n "$NAMESPACE" -l "$selector" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [[ -n "$POD" ]]; then
    info "Pod: $POD"
    kubectl logs -n "$NAMESPACE" "$POD" --tail="$TAIL" 2>/dev/null || warn "로그 없음"
  else
    warn "$label Pod 없음"
  fi
}

case "$TARGET" in
  hub)      show_logs "central-hub"         "app=central-hub" ;;
  edge)     show_logs "edge-broadcaster"    "app=edge-broadcaster" ;;
  robot)    show_logs "mission-listener"    "app=mission-listener" ;;
  rssi)     show_logs "rssi-collector"      "app=rssi-collector" ;;
  handover) show_logs "handover-controller" "app=handover-controller" ;;
  fallback) show_logs "fallback-controller" "app=fallback-controller" ;;
  all|*)
    show_logs "central-hub"         "app=central-hub"
    show_logs "edge-broadcaster"    "app=edge-broadcaster"
    show_logs "rssi-collector"      "app=rssi-collector"
    show_logs "handover-controller" "app=handover-controller"
    show_logs "mission-listener"    "app=mission-listener"
    show_logs "fallback-controller" "app=fallback-controller"
    ;;
esac
