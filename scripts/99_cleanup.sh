#!/usr/bin/env bash
# 99_cleanup.sh — 전체 배포 정리
#
# 사용법:
#   bash scripts/99_cleanup.sh              # 전체 정리
#   bash scripts/99_cleanup.sh infra        # Redis + Hub만
#   bash scripts/99_cleanup.sh edge         # edge 서비스만
#   bash scripts/99_cleanup.sh robot        # robot 서비스만
#   bash scripts/99_cleanup.sh missions     # 미션 Pod + Redis 키만
#   bash scripts/99_cleanup.sh redis-keys   # Redis 키만 (Pod 유지)
set -euo pipefail
source "$(dirname "$0")/common.sh"

TARGET="${1:-all}"

del() {
  local kind="$1" name="$2"
  if kubectl get "$kind" "$name" -n "$NAMESPACE" &>/dev/null 2>&1; then
    kubectl delete "$kind" "$name" -n "$NAMESPACE" --ignore-not-found
    ok "  삭제: $kind/$name"
  else
    info "  없음: $kind/$name (skip)"
  fi
}

flush_redis() {
  local pattern="$1"
  local REDIS_POD
  REDIS_POD=$(kubectl get pod -n "$NAMESPACE" -l app=redis \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
  if [[ -z "$REDIS_POD" ]]; then
    warn "Redis Pod 없음 — 키 정리 스킵"
    return
  fi
  local KEYS
  KEYS=$(kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
    redis-cli keys "$pattern" 2>/dev/null || echo "")
  if [[ -n "$KEYS" ]]; then
    echo "$KEYS" | while read -r key; do
      [[ -z "$key" ]] && continue
      kubectl exec -n "$NAMESPACE" "$REDIS_POD" -- \
        redis-cli del "$key" &>/dev/null
      info "  Redis 삭제: $key"
    done
  else
    info "  패턴($pattern) 해당 키 없음"
  fi
}

case "$TARGET" in
  infra)
    section "인프라 정리 (Redis + central-hub)"
    del deployment central-hub
    del service    central-hub
    del deployment redis-deployment
    del service    redis-service
    del configmap  fleet-config
    del configmap  robot-config
    ;;

  edge)
    section "edge 서비스 정리 (Phase 1 + Phase 2)"
    del daemonset edge-broadcaster
    del daemonset rssi-collector
    del daemonset handover-controller
    ;;

  robot)
    section "robot 서비스 정리 (Phase 1 + Phase 2)"
    del daemonset mission-listener
    del daemonset fallback-controller
    ;;

  missions)
    section "미션 Pod 정리"
    kubectl delete pod -n "$NAMESPACE" -l app=mission-task --ignore-not-found || true
    ok "미션 Pod 삭제"
    section "Redis 미션 키 정리"
    flush_redis "mission:*"
    flush_redis "mission_result:*"
    flush_redis "fleet:cache:*"
    flush_redis "handover:*"
    ;;

  redis-keys)
    section "Redis 키 전체 정리 (Pod 유지)"
    for pattern in "mission:*" "mission_result:*" "fleet:*" \
                   "robot:*" "rssi:*" "handover:*" "link_status:*"; do
      flush_redis "$pattern"
    done
    ok "Redis 키 정리 완료"
    ;;

  all|*)
    section "전체 정리"

    # Phase 2 서비스
    del daemonset rssi-collector
    del daemonset handover-controller
    del daemonset fallback-controller

    # Phase 1 서비스
    del daemonset  edge-broadcaster
    del daemonset  mission-listener
    del daemonset  central-robot-detector 
    kubectl delete daemonset robot-detector -n default --ignore-not-found || true
    kubectl delete pod -n "$NAMESPACE" -l app=mission-task --ignore-not-found || true

    # 인프라
    del deployment central-hub
    del service    central-hub
    del deployment redis-deployment
    del service    redis-service
    del configmap  fleet-config
    del configmap  robot-config
    del serviceaccount central-hub-sa
    kubectl delete clusterrole    central-hub-sa-manager-role     --ignore-not-found || true
    kubectl delete clusterrolebinding central-hub-sa-manager-binding --ignore-not-found || true
    ;;
esac

section "정리 후 상태"
kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || true
ok "정리 완료"
