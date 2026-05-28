#!/usr/bin/env bash
# cleanup_deprecated.sh
# 불필요한 파일과 폴더를 실제로 삭제합니다.
# 반드시 fleet_mission_dashboard/ 루트에서 실행하세요.
#
# 사용법:
#   bash scripts/cleanup_deprecated.sh          # 미리보기 (dry-run)
#   bash scripts/cleanup_deprecated.sh --apply  # 실제 삭제

set -euo pipefail
cd "$(dirname "$0")/.."

DRY_RUN=true
if [[ "${1:-}" == "--apply" ]]; then
  DRY_RUN=false
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info() { echo -e "${CYAN}[DRY]${RESET}  $*"; }
del()  {
  if $DRY_RUN; then
    echo -e "${YELLOW}[삭제 예정]${RESET}  $*"
  else
    if [[ -e "$*" ]]; then
      rm -rf "$*"
      echo -e "${RED}[삭제됨]${RESET}    $*"
    else
      echo -e "${GREEN}[없음-skip]${RESET} $*"
    fi
  fi
}

echo ""
echo "════════════════════════════════════════"
echo "  파일 정리 $([ "$DRY_RUN" = true ] && echo '(미리보기 — 실제 삭제 안 함)' || echo '(실제 삭제)')"
echo "════════════════════════════════════════"
echo ""

# ── 1. robot-detector (broadcaster로 완전 대체) ──────────────────
echo "▸ apps/robot-detector 전체"
del apps/robot-detector

# ── 2. __pycache__ 전체 ──────────────────────────────────────────
echo "▸ 모든 __pycache__"
if $DRY_RUN; then
  find . -type d -name __pycache__ | while read -r d; do echo -e "${YELLOW}[삭제 예정]${RESET}  $d"; done
else
  find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
  echo -e "${RED}[삭제됨]${RESET}    모든 __pycache__"
fi

# ── 3. deprecated scripts (숫자 중복·구 버전) ────────────────────
echo "▸ deprecated scripts"
del scripts/01_render_manifests.sh
del scripts/02_build_images.sh
del scripts/03_push_images.sh
del scripts/04_deploy_k3s.sh
del scripts/05_check_status.sh
del scripts/06_port_forward_hub.sh
del scripts/07_run_webui.sh
del scripts/08_pygui_headless.sh
del scripts/10_run_webui.sh
del scripts/test_guid.txt

# ── 4. tools/ 불필요 파일 ────────────────────────────────────────
echo "▸ tools/ 불필요 파일"
del tools/pygui.py
del tools/render_manifests.py
del tools/_bc_conditions_patch.txt

# ── 5. 루트 잡동사니 ─────────────────────────────────────────────
echo "▸ 루트 불필요 파일"
del requirements-pygui.txt
del requirements-webui.txt
del README-webui.md

# ── 6. apps/central-hub 구 파일 ──────────────────────────────────
echo "▸ apps/central-hub 구 파일"
del apps/central-hub/mission_policy.yaml

# ── 7. 빈 서비스 폴더 (Phase 2에서 새로 만들 예정) ───────────────
echo "▸ 빈 서비스 폴더"
del services/handover-controller
del services/health-agent
del services/mission-operator
del services/telemetry-agent

# ── 8. 빈 config 하위 폴더 ───────────────────────────────────────
echo "▸ 빈 config 하위 폴더"
del config/robots
del config/stations

# ── 9. 빈 deploy 하위 폴더 ───────────────────────────────────────
echo "▸ 빈 deploy 하위 폴더"
del deploy/base/rbac
del deploy/cloud
del shared

echo ""
echo "════════════════════════════════════════"
if $DRY_RUN; then
  echo -e "${YELLOW}  미리보기 완료 — 실제 삭제하려면:${RESET}"
  echo "  bash scripts/cleanup_deprecated.sh --apply"
else
  echo -e "${GREEN}  정리 완료${RESET}"
fi
echo "════════════════════════════════════════"
