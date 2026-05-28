#!/usr/bin/env bash
# 06_push_images.sh — 빌드된 이미지를 레지스트리에 푸시
# 멀티플랫폼(buildx) 빌드는 05_build_images.sh에서 --push로 직접 처리
# 이 스크립트는 단일 플랫폼 로컬 빌드 후 push할 때 사용
set -euo pipefail
source "$(dirname "$0")/common.sh"

section "이미지 푸시"

push_image() {
  local label="$1"
  local image="$2"
  info "Pushing $label: $image"
  docker push "$image"
  ok "  $label push 완료"
}

push_image "central-hub"      "$(cfg images.central_hub)"
push_image "edge-broadcaster" "$(cfg images.broadcaster)"
push_image "mission-listener" "$(cfg images.mission_listener)"

ok "모든 이미지 푸시 완료"
