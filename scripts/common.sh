#!/usr/bin/env bash
# common.sh — 모든 스크립트 공통 기반
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CONFIG_PATH="${CONFIG_PATH:-$ROOT_DIR/config.yaml}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
err()     { echo -e "${RED}[ERR]${RESET}   $*" >&2; }
section() { echo -e "\n${BOLD}━━━ $* ━━━${RESET}"; }

cfg() {
  python3 - "$1" <<'PY'
import sys
from tools.config_loader import load_config
val = load_config().get(sys.argv[1], "")
if isinstance(val, bool): print(str(val).lower())
elif val is None: print("")
else: print(val)
PY
}

# 공통 변수
NAMESPACE="${NAMESPACE:-$(cfg network.namespace)}"
HUB_PORT="$(cfg network.hub_port)"          # NodePort (외부 접근)
HUB_BIND_PORT="${HUB_BIND_PORT:-$(cfg network.hub_bind_port)}" # FastAPI 내부 포트
MQTT_HOST="$(cfg mqtt.host)"
MQTT_PORT="$(cfg mqtt.port)"

TOPIC_DEPLOY="fleet/mission/deploy"
TOPIC_BROADCAST="fleet/mission/broadcast"
TOPIC_ACCEPT="fleet/mission/accept/#"
TOPIC_CACHE="fleet/mission/cache/#"
TOPIC_ACCEPTED="fleet/mission/accepted"

# force_ds_image — DaemonSet의 컨테이너 이미지를 config 값으로 강제 반영.
# 배포 매니페스트의 이미지 태그가 오래됐을 때 config.yaml 기준으로 덮어쓴다.
#   $1: DaemonSet 이름, $2: 적용할 이미지 (비어 있으면 skip)
force_ds_image() {
  local ds="$1" image="$2"

  if [[ -z "$image" || "$image" == "null" ]]; then
    warn "$ds 이미지 config 없음 — skip"
    return 0
  fi

  local cname
  cname=$(kubectl get daemonset "$ds" -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null || echo "")

  if [[ -z "$cname" ]]; then
    warn "$ds 컨테이너 이름 확인 실패 — skip"
    return 0
  fi

  kubectl set image daemonset/"$ds" -n "$NAMESPACE" "$cname=$image"
  kubectl patch daemonset "$ds" -n "$NAMESPACE" --type=json \
    -p='[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Always"}]' \
    >/dev/null || true

  ok "$ds 이미지 적용: $image"
}
