#!/usr/bin/env bash
# 03_deploy_edge.sh — edge 노드 서비스 배포
# Phase 1: edge-broadcaster
# Phase 2: rssi-collector, handover-controller
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "edge 노드 서비스 배포"

EDGE_NODE_COUNT=$(kubectl get nodes -l node-role=edge --no-headers 2>/dev/null | wc -l | tr -d ' ')
if [[ "$EDGE_NODE_COUNT" -eq 0 ]]; then
  err "node-role=edge 라벨 노드 없음 → 01_label_nodes.sh 먼저 실행"
  exit 1
fi
info "edge 노드 수: ${EDGE_NODE_COUNT}개"

# ── Phase 1: broadcaster ─────────────────────────────────────────
kubectl apply -f deploy/edge/broadcaster-daemonset.yaml
ok "broadcaster DaemonSet 적용"

# ── Phase 2: rssi-collector + handover-controller ────────────────
kubectl apply -f deploy/edge/phase2-daemonsets.yaml
ok "Phase 2 DaemonSets 적용 (rssi-collector, handover-controller)"

# ── 이미지 태그 강제 반영 (force_ds_image는 common.sh 정의) ──────
force_ds_image edge-broadcaster "$(cfg images.broadcaster)"
force_ds_image rssi-collector "$(cfg images.rssi_collector)"
force_ds_image handover-controller "$(cfg images.handover_controller)"


info "DaemonSet 준비 대기 (최대 60초)..."
kubectl rollout status daemonset/edge-broadcaster   -n "$NAMESPACE" --timeout=60s || true
kubectl rollout status daemonset/rssi-collector     -n "$NAMESPACE" --timeout=60s || true
kubectl rollout status daemonset/handover-controller -n "$NAMESPACE" --timeout=60s || true

section "edge Pod 상태"
kubectl get pods -n "$NAMESPACE" -l 'app in (edge-broadcaster,rssi-collector,handover-controller)' -o wide

ok "완료 — 다음: bash scripts/04_deploy_robot.sh"
