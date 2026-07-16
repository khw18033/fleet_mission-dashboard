#!/usr/bin/env bash
# 04_deploy_robot.sh — robot 노드 서비스 배포
# Phase 1: mission-listener
# Phase 2: fallback-controller
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "robot 노드 서비스 배포"

ROBOT_NODE_COUNT=$(kubectl get nodes -l node-role=robot --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$ROBOT_NODE_COUNT" -eq 0 ]]; then
  err "node-role=robot 라벨 노드 없음 → 01_label_nodes.sh 먼저 실행"
  exit 1
fi
info "robot 노드 수: ${ROBOT_NODE_COUNT}개"

# ── Phase 1: mission-listener ─────────────────────────────────────
kubectl apply -f deploy/robot/listener-daemonset.yaml
ok "mission-listener DaemonSet 적용"

# ── Phase 2: fallback-controller ─────────────────────────────────
kubectl apply -f deploy/robot/fallback-controller-daemonset.yaml
ok "fallback-controller DaemonSet 적용"

# ── 이미지 태그 강제 반영 (force_ds_image는 common.sh 정의) ──────
force_ds_image mission-listener "$(cfg images.mission_listener)"
force_ds_image fallback-controller "$(cfg images.fallback_controller)"


info "DaemonSet 준비 대기 (최대 60초)..."
kubectl rollout status daemonset/mission-listener    -n "$NAMESPACE" --timeout=60s || true
kubectl rollout status daemonset/fallback-controller -n "$NAMESPACE" --timeout=60s || true

section "robot Pod 상태"
kubectl get pods -n "$NAMESPACE" -l 'app in (mission-listener,fallback-controller)' -o wide

ok "완료 — 다음: bash scripts/07_status.sh"
