#!/usr/bin/env bash
# 01_label_nodes.sh — k3s 노드에 role 라벨 부여
# edge 노드는 broadcaster, robot 노드는 listener DaemonSet이 배포됨
#
# 사용법:
#   bash scripts/01_label_nodes.sh                  # 대화형 모드
#   EDGE_NODES="pi1 pi2" ROBOT_NODES="pi3 pi4" bash scripts/01_label_nodes.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "k3s 노드 역할 라벨링"

info "현재 노드 목록:"
kubectl get nodes -o wide

echo ""

# ── 환경변수로 전달받거나 대화형으로 입력 ────────────────────────
if [[ -z "${EDGE_NODES:-}" ]]; then
  info "기지국(edge) 노드 이름을 입력하세요 (공백 구분, 예: pi1 pi2)"
  read -r -p "  edge nodes: " EDGE_NODES
fi

if [[ -z "${ROBOT_NODES:-}" ]]; then
  info "제어용(robot) 노드 이름을 입력하세요 (공백 구분, 예: pi3 pi4)"
  read -r -p "  robot nodes: " ROBOT_NODES
fi

# ── edge 라벨 부여 ───────────────────────────────────────────────
section "edge 노드 라벨 적용"
for node in $EDGE_NODES; do
  if kubectl get node "$node" &>/dev/null; then
    kubectl label node "$node" node-role=edge --overwrite
    ok "  $node → node-role=edge"
  else
    err "  노드 '$node' 를 찾을 수 없음"
    exit 1
  fi
done

# ── robot 라벨 부여 ──────────────────────────────────────────────
section "robot 노드 라벨 적용"
for node in $ROBOT_NODES; do
  if kubectl get node "$node" &>/dev/null; then
    kubectl label node "$node" node-role=robot --overwrite
    ok "  $node → node-role=robot"
  else
    err "  노드 '$node' 를 찾을 수 없음"
    exit 1
  fi
done

section "라벨 확인"
kubectl get nodes -L node-role

ok "완료 — 다음 단계: bash scripts/02_deploy_infra.sh"
