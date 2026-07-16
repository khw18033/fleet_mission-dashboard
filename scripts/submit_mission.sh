#!/usr/bin/env bash
# submit_mission.sh — JSON 미션 문서를 허브에 제출 (UI 없이)
#
# 미션을 노드 라벨 또는 노드/기지국 이름으로 타깃팅해 배포한다.
# 미션 문서 형식은 missions/example.mission.json 참조.
#
# 사용법:
#   bash scripts/submit_mission.sh <mission.json> [옵션]
#
# 타깃 옵션 (하나만):
#   --node-label KEY=VAL   해당 라벨의 노드들로 타깃팅 (kubectl로 노드명 해석)
#   --stations a,b         노드/기지국 이름을 직접 지정 (쉼표 구분)
#   (생략 시 문서의 target_stations 사용, 그것도 없으면 전체 브로드캐스트)
#
# 환경변수:
#   HUB_URL   허브 주소 직접 지정 (기본: central-hub Pod hostIP:node_port)
#
# 예시:
#   bash scripts/submit_mission.sh missions/example.mission.json --node-label node-role=edge
#   bash scripts/submit_mission.sh missions/example.mission.json --stations pi3,pi4
#   HUB_URL=http://localhost:5001 bash scripts/submit_mission.sh missions/example.mission.json
set -euo pipefail
source "$(dirname "$0")/common.sh"

MISSION_FILE="${1:-}"
if [[ -z "$MISSION_FILE" || ! -f "$MISSION_FILE" ]]; then
  err "미션 JSON 문서 경로가 필요합니다."
  echo "사용법: bash scripts/submit_mission.sh <mission.json> [--node-label KEY=VAL | --stations a,b]"
  exit 1
fi
shift

NODE_LABEL=""
STATIONS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --node-label) NODE_LABEL="${2:-}"; shift 2 ;;
    --stations)   STATIONS="${2:-}";   shift 2 ;;
    *) err "알 수 없는 옵션: $1"; exit 1 ;;
  esac
done

# ── 타깃 노드 해석 ───────────────────────────────────────────────
TARGET_STATIONS=""   # 쉼표 구분 문자열
if [[ -n "$NODE_LABEL" ]]; then
  section "노드 라벨 해석: $NODE_LABEL"
  NODES=$(kubectl get nodes -l "$NODE_LABEL" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
  if [[ -z "$NODES" ]]; then
    err "라벨 '$NODE_LABEL' 에 해당하는 노드가 없습니다."
    exit 1
  fi
  TARGET_STATIONS=$(echo "$NODES" | tr ' ' ',')
  ok "타깃 노드: $TARGET_STATIONS"
elif [[ -n "$STATIONS" ]]; then
  TARGET_STATIONS="$STATIONS"
  info "타깃 지정: $TARGET_STATIONS"
fi

# ── 허브 URL ─────────────────────────────────────────────────────
if [[ -z "${HUB_URL:-}" ]]; then
  HUB_NODE=$(kubectl get pod -n "$NAMESPACE" -l app=central-hub \
    -o jsonpath='{.items[0].status.hostIP}' 2>/dev/null || echo "localhost")
  HUB_URL="http://${HUB_NODE}:$(cfg kubernetes.node_port)"
fi
info "Hub URL: $HUB_URL"

# ── 미션 문서에 target_stations 병합 후 페이로드 생성 ────────────
PAYLOAD=$(TARGET_STATIONS="$TARGET_STATIONS" python3 - "$MISSION_FILE" <<'PY'
import json, os, sys
with open(sys.argv[1], encoding='utf-8') as f:
    doc = json.load(f)
if not isinstance(doc.get('nodes'), list) or not doc['nodes']:
    print('MISSION_ERROR: 문서에 nodes 배열이 필요합니다', file=sys.stderr); sys.exit(2)
ts = os.environ.get('TARGET_STATIONS', '').strip()
if ts:
    doc['target_stations'] = [s for s in ts.split(',') if s]
doc.setdefault('target_stations', doc.get('target_stations', []))
print(json.dumps(doc, ensure_ascii=False))
PY
)

section "미션 제출"
info "문서:   $MISSION_FILE"
info "노드수: $(echo "$PAYLOAD" | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("nodes",[])))')"

RESPONSE=$(curl -s -X POST "$HUB_URL/api/missions/broadcast" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" --max-time 10 || echo '{"status":"error","message":"curl failed"}')

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

if echo "$RESPONSE" | grep -q '"status": *"success"'; then
  ok "미션 제출 성공"
else
  err "미션 제출 실패 — 응답 확인"
  exit 1
fi
