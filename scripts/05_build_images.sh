#!/usr/bin/env bash
# 05_build_images.sh — 전체 이미지 빌드/푸시
#
# 사용법:
#   bash scripts/05_build_images.sh
#   PLATFORM=linux/arm64 bash scripts/05_build_images.sh
#   PLATFORM=linux/amd64,linux/arm64 bash scripts/05_build_images.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

source "$SCRIPT_DIR/common.sh"

PLATFORM="${PLATFORM:-linux/amd64}"
info "빌드 플랫폼: $PLATFORM"

# ────────────────────────────────────────────────────────────────
# React SPA 빌드
# ────────────────────────────────────────────────────────────────
section "React SPA 빌드"

if command -v node &>/dev/null && command -v npm &>/dev/null && [[ -f "$ROOT_DIR/ui-spa/package.json" ]]; then
  info "npm install + build..."
  (
    cd "$ROOT_DIR/ui-spa"
    npm install
    npm run build
  )
  ok "SPA 빌드 완료 → ui-spa/dist/"
else
  warn "Node.js/npm 없음 또는 ui-spa/package.json 없음 — SPA 빌드 스킵"
fi

# ────────────────────────────────────────────────────────────────
# buildx 설정
# ────────────────────────────────────────────────────────────────
USE_BUILDX=0

if [[ "$PLATFORM" == *","* ]] || [[ "$PLATFORM" == *"arm64"* ]]; then
  USE_BUILDX=1
  section "Docker buildx 설정"

  if ! docker buildx inspect fleet-builder &>/dev/null; then
    info "fleet-builder 생성"
    docker buildx create --name fleet-builder --use
    docker buildx inspect --bootstrap
  else
    docker buildx use fleet-builder
  fi

  info "멀티플랫폼/ARM 빌드 모드 — registry push"
else
  info "단일 플랫폼 빌드 모드 — local image"
fi

# ────────────────────────────────────────────────────────────────
# 이미지 빌드 함수
# ────────────────────────────────────────────────────────────────
build_image() {
  local label="$1"
  local image_key="$2"
  local context_key="$3"

  local image
  local context
  local dockerfile

  image="$(cfg "images.${image_key}" || true)"
  context="$(cfg "docker.build_contexts.${context_key}" || true)"

  if [[ -z "$image" || "$image" == "null" ]]; then
    warn "$label 스킵 — config 누락: images.${image_key}"
    return 0
  fi

  if [[ -z "$context" || "$context" == "null" ]]; then
    warn "$label 스킵 — config 누락: docker.build_contexts.${context_key}"
    return 0
  fi

  dockerfile="${context}/Dockerfile"

  case "$context_key" in
    central_hub)
      dockerfile="apps/central-hub/Dockerfile"
      context="."
      ;;
    broadcaster)
      dockerfile="services/edge-gateway/Dockerfile"
      context="."
      ;;
    mission_listener)
      dockerfile="services/mission-listener/Dockerfile"
      context="."
      ;;
    link_proxy)
      dockerfile="apps/brain-ep01/link/Dockerfile"
      context="."
      ;;
    nav_worker)
      dockerfile="apps/brain-ep01/tasks/navigation/Dockerfile"
      context="apps/brain-ep01/tasks/navigation"
      ;;
    vision_worker)
      dockerfile="apps/brain-ep01/tasks/vision/Dockerfile"
      context="apps/brain-ep01/tasks/vision"
      ;;
    rssi_collector)
      dockerfile="services/rssi_collector/Dockerfile"
      context="."
      ;;
    handover_controller)
      dockerfile="services/handover_controller/Dockerfile"
      context="."
      ;;
    fallback_controller)
      dockerfile="services/fallback_controller/Dockerfile"
      context="."
      ;;
  esac

  section "빌드: $label"
  info "  이미지:     $image"
  info "  컨텍스트:   $context"
  info "  Dockerfile: $dockerfile"

  if [[ ! -d "$ROOT_DIR/$context" ]]; then
    warn "$label 스킵 — 컨텍스트 디렉터리 없음: $context"
    return 0
  fi

  if [[ ! -f "$ROOT_DIR/$dockerfile" ]]; then
    warn "$label 스킵 — Dockerfile 없음: $dockerfile"
    return 0
  fi

  if [[ "$USE_BUILDX" -eq 1 ]]; then
    docker buildx build \
      --platform "$PLATFORM" \
      --push \
      -t "$image" \
      -f "$ROOT_DIR/$dockerfile" \
      "$ROOT_DIR/$context"
  else
    docker build \
      --platform "$PLATFORM" \
      -t "$image" \
      -f "$ROOT_DIR/$dockerfile" \
      "$ROOT_DIR/$context"
  fi

  ok "$label 빌드 완료"
}

# ────────────────────────────────────────────────────────────────
# Phase 1: 핵심 런타임
# ────────────────────────────────────────────────────────────────
section "Phase 1 이미지 빌드"

build_image "central-hub"       "central_hub"       "central_hub"
build_image "edge-broadcaster"  "broadcaster"       "broadcaster"
build_image "mission-listener"  "mission_listener"  "mission_listener"
build_image "link-proxy"        "link_proxy"        "link_proxy"
build_image "nav-worker"        "nav_worker"        "nav_worker"
build_image "vision-worker"     "vision_worker"     "vision_worker"

# ────────────────────────────────────────────────────────────────
# Phase 2: 선택 기능
# config.yaml에 image/context가 있을 때만 빌드
# ────────────────────────────────────────────────────────────────
section "Phase 2 이미지 빌드"

build_image "rssi-collector"       "rssi_collector"       "rssi_collector"
build_image "handover-controller"  "handover_controller"  "handover_controller"
build_image "fallback-controller"  "fallback_controller"  "fallback_controller"

section "로컬 이미지 목록"
docker images | grep -E "central-hub|ep01-link|nav-worker|vision-worker|broadcaster|listener|rssi|handover|fallback" || true

ok "전체 빌드 완료"

if [[ "$USE_BUILDX" -eq 0 ]]; then
  info "단일 플랫폼 로컬 빌드 완료. 필요 시 다음 실행:"
  info "  bash scripts/06_push_images.sh"
fi