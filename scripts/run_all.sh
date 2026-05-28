#!/usr/bin/env bash
# run_all.sh — 전체 배포 한 번에 (이미지 빌드/푸시 제외)
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "════════════════════════════════════════"
echo "  Fleet Mission System — 전체 배포"
echo "  Phase 1 + Phase 2"
echo "════════════════════════════════════════"

bash "$SCRIPTS_DIR/00_check_prereqs.sh"
bash "$SCRIPTS_DIR/01_label_nodes.sh"
bash "$SCRIPTS_DIR/02_deploy_infra.sh"
bash "$SCRIPTS_DIR/03_deploy_edge.sh"   # broadcaster + rssi + handover
bash "$SCRIPTS_DIR/04_deploy_robot.sh"  # listener + fallback
bash "$SCRIPTS_DIR/07_status.sh"

echo ""
echo "════════════════════════════════════════"
echo "  배포 완료"
echo ""
echo "  UI:               bash scripts/11_run_webui.sh"
echo "  개발 모드:         DEV=1 bash scripts/11_run_webui.sh"
echo "  E2E 테스트:        bash scripts/10_e2e_robot_test.sh"
echo "  핸드오버 테스트:   bash scripts/13_test_handover.sh"
echo "  파이프라인 테스트: bash scripts/09_test_pipeline.sh"
echo "  로그:              bash scripts/08_logs.sh [hub|edge|robot|rssi|handover|fallback]"
echo "  정리:              bash scripts/99_cleanup.sh"
echo "════════════════════════════════════════"
