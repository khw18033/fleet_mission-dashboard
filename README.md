# Fleet Mission — Admin (플랫폼/관리자)

여러 대의 로봇과 기지국(엣지)을 관제하는 **플랫폼/관리 기능**입니다. 중앙 허브,
기지국·로봇 노드 서비스, k3s 배포 매니페스트, 운영 스크립트, 그리고 로봇과의
[제어 프로토콜](protocol/PROTOCOL.md)을 담습니다. 중앙 허브가 미션을 브로드캐스트하면
기지국이 중계하고, 각 로봇의 제어 노드가 조건을 평가해 수락/거절한 뒤 실행합니다.
RSSI 기반 기지국 핸드오버와 서버 단절 시 자동 fallback을 지원합니다.

> 이 브랜치는 모노레포를 책임별로 분리한 `admin` 브랜치입니다.
> 로봇 SDK/제어 어댑터는 `robot-image`, 대시보드 UI는 `ui` 브랜치를 참조하세요.
> 관리자는 이 프로토콜과 노드만 관리하고, 로봇 담당자는 프로토콜을 지키는 어댑터를
> 자유 SDK로 구현합니다.

## 구성

| 경로 | 설명 |
| --- | --- |
| `apps/central-hub` | FastAPI 기반 중앙 허브. REST/WebSocket API, MQTT/Redis 연동, SPA 서빙 |
| `services/mission-listener` | 제어용 RPi. 미션 수신 → 조건 평가 → accept/reject → 명령 큐 발행 |
| `services/edge-gateway` | 기지국 RPi. 허브 미션을 로봇에 브로드캐스트하고 결과를 중계 |
| `services/rssi_collector` | 기지국에서 로봇 AP의 RSSI를 스캔·평활화해 Redis에 기록 |
| `services/handover_controller` | RSSI를 비교해 더 강한 기지국으로 핸드오버 트리거 |
| `services/fallback_controller` | 서버 단절 감지 시 `last-mission.json` 자동 실행 |
| `deploy/*` | k3s 배포용 Kubernetes 매니페스트와 ConfigMap |
| `scripts/*` | 배포, 점검, 테스트, 정리용 셸 스크립트 |
| `protocol/*` | 로봇 어댑터와의 SDK 독립 제어 프로토콜(계약) 문서·스키마 |
| `tools/config_loader.py` | `config.yaml`을 점 표기법(`network.redis_host`)으로 읽는 공용 로더 |

## 메시지 흐름

```
[중앙 허브] --fleet/mission/deploy--> [기지국 broadcaster]
                                        --fleet/mission/broadcast--> [로봇 listener]
[로봇 listener] --fleet/mission/accept/{station}--> [broadcaster]
                                        --fleet/mission/accepted--> [중앙 허브]
[로봇 listener] --fleet/mission/cache/{robot}--> [broadcaster/허브] (체크포인트)

핸드오버: [handover_controller] --fleet/handover/prewarm/{station}--> [broadcaster]
                                --fleet/handover/{robot}--> [listener]
```

## 클러스터 구성 (Tailscale + k3s)

여러 대의 라즈베리파이/노드를 Tailscale VPN으로 묶고 k3s 클러스터를 구성한 뒤,
역할 라벨을 지정하는 순서입니다.

### 1. Tailscale VPN 연결

모든 노드(서버 + 각 라즈베리파이)에서 동일한 Tailnet에 로그인해 사설 IP로 연결합니다.

```bash
# 각 노드에서 설치 및 로그인 (동일 계정/Tailnet)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# 노드의 Tailscale IP 확인 (100.x.y.z 대역)
tailscale ip -4
tailscale status          # Tailnet의 모든 노드와 온라인 여부
```

k3s 노드 간 통신은 이 Tailscale IP(`100.x.y.z`)를 사용하면 방화벽/NAT 없이 안정적입니다.

### 2. k3s 설치 (서버 1대 + 에이전트 N대)

```bash
# (서버 노드) — Tailscale IP를 노드 IP로 광고
curl -sfL https://get.k3s.io | \
  INSTALL_K3S_EXEC="--node-ip $(tailscale ip -4) --flannel-iface tailscale0" sh -

# 조인 토큰과 서버 IP 확인
sudo cat /var/lib/rancher/k3s/server/node-token
SERVER_IP=$(tailscale ip -4)

# (각 에이전트/로봇·기지국 노드)
curl -sfL https://get.k3s.io | \
  K3S_URL="https://${SERVER_IP}:6443" \
  K3S_TOKEN="<서버 node-token>" \
  INSTALL_K3S_EXEC="--node-ip $(tailscale ip -4) --flannel-iface tailscale0" sh -
```

서버에서 kubeconfig는 `/etc/rancher/k3s/k3s.yaml` 에 있습니다. 로컬 `kubectl`로 쓰려면:

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
# 원격에서 접근 시 k3s.yaml의 server: 주소를 서버의 Tailscale IP로 바꿔 복사
```

### 3. 노드 역할 라벨 지정

기지국은 `node-role=edge`, 제어용 로봇 노드는 `node-role=robot` 라벨을 답니다.
DaemonSet들이 이 라벨을 `nodeSelector`로 사용합니다.

```bash
# 대화형 또는 환경변수로 일괄 지정 (스크립트 제공)
EDGE_NODES="pi-edge1 pi-edge2" ROBOT_NODES="pi-robot1 pi-robot2" \
  bash scripts/01_label_nodes.sh

# 수동 지정
kubectl label node <노드이름> node-role=edge  --overwrite
kubectl label node <노드이름> node-role=robot --overwrite

# 라벨 확인
kubectl get nodes -L node-role
```

### 4. 기본 kubectl 명령어

```bash
# 노드
kubectl get nodes -o wide            # 노드 목록/IP/상태
kubectl get nodes -L node-role       # 역할 라벨과 함께
kubectl describe node <노드이름>      # 노드 상세(리소스/조건/파드)

# 파드
kubectl get pods -n centralized -o wide          # 네임스페이스 파드 목록
kubectl get pods -A                              # 전체 네임스페이스
kubectl get pods -n centralized -l app=central-hub   # 라벨 셀렉터
kubectl describe pod <파드이름> -n centralized    # 파드 상세/이벤트

# 로그 / 접속 / 디버깅
kubectl logs -n centralized <파드이름> -f         # 실시간 로그 (또는 scripts/08_logs.sh)
kubectl exec -it -n centralized <파드이름> -- sh  # 컨테이너 접속
kubectl get svc,daemonset,configmap -n centralized  # 서비스/데몬셋/컨피그맵

# 배포 상태 / 롤아웃
kubectl rollout status daemonset/mission-listener -n centralized
kubectl apply -f deploy/edge/broadcaster-daemonset.yaml   # 매니페스트 적용
kubectl delete pod <파드이름> -n centralized      # 파드 재시작(자동 재생성)
```

클러스터 전반 상태는 `bash scripts/07_status.sh`, 사전 점검은
`bash scripts/00_check_prereqs.sh`로 한 번에 확인할 수 있습니다.

## 설정 (config.yaml)

비공개 값은 저장소에 커밋하지 않습니다. `config.example.yaml`을 복사해 로컬 값으로 채우세요.

```bash
cp config.example.yaml config.yaml
```

주요 키:

- `network.*` — Redis 호스트/포트, 허브 바인드 포트, 네임스페이스
- `mqtt.*` — MQTT 브로커 호스트/포트/keepalive
- `stations[]` — 기지국 ID·노드 이름·스캔/제어 인터페이스
- `robot.ap.ssid_to_sn` — 로봇 AP SSID ↔ 시리얼번호(SN) 매핑
- `services.rssi.*`, `services.handover.*` — RSSI 평활화·핸드오버 임계값
- `images.*` — 각 서비스의 컨테이너 이미지 태그

설정 파일 위치는 `CONFIG_PATH` 환경변수로 덮어쓸 수 있으며, 없으면 저장소 트리에서
`config.yaml`을 상향 탐색합니다.

## 주요 환경변수

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `CONFIG_PATH` | (자동 탐색) | 사용할 `config.yaml` 경로 |
| `MOCK_MODE` | `0` | `1`이면 MQTT/Redis/장비 없이 import·기본 동작만 수행 |
| `DEV` | `0` | 웹 UI를 개발 모드로 실행 |
| `WEBUI_PORT` | `5001` | 웹 UI(FastAPI) 포트 |
| `K3S_DRY_RUN` | `0` | k8s 연결 없이 허브 기동 |
| `MQTT_HOST` / `MQTT_PORT` | config 값 | MQTT 브로커 오버라이드 |
| `REDIS_HOST` / `REDIS_PORT` | config 값 | Redis 오버라이드 |
| `STATION_ID` | `station-a` | 기지국 서비스가 사용하는 기지국 ID |
| `ROBOT_ID` | config 값 | 로봇 서비스가 사용하는 로봇 SN |

## 시작하기

```bash
cp config.example.yaml config.yaml     # 로컬 환경 값으로 수정
bash scripts/00_check_prereqs.sh       # 필요한 도구 점검
```

## 실행

### 웹 UI

```bash
bash scripts/11_run_webui.sh           # 허브 API + 빌드된 SPA
DEV=1 bash scripts/11_run_webui.sh     # 개발 모드(Vite :5173 + FastAPI)
```

기본 포트는 `WEBUI_PORT`(기본값 `5001`)이며 환경변수로 바꿀 수 있습니다.
개발 모드에서는 UI가 `http://localhost:5173`, API가 `http://localhost:5001`에 뜹니다.
빌드된 SPA가 없으면 프로덕션 모드 첫 실행 시 자동으로 `npm install && npm run build`를 수행합니다.

### 전체 배포

```bash
bash scripts/run_all.sh
```

## 스크립트

번호 순서대로 실행하면 배포 파이프라인이 완성됩니다. `scripts/common.sh`가 공통
로깅·config 조회(`cfg`)·이미지 반영(`force_ds_image`) 함수를 제공합니다.

| 스크립트 | 역할 |
| --- | --- |
| `00_check_prereqs.sh` | 필수 도구·Python 패키지·k3s·MQTT·config 점검 |
| `01_label_nodes.sh` | 노드에 `node-role=edge`/`node-role=robot` 라벨 부여 |
| `02_deploy_infra.sh` | ConfigMap·RBAC·Redis·central-hub 배포 |
| `03_deploy_edge.sh` | broadcaster·rssi-collector·handover-controller 배포 |
| `04_deploy_robot.sh` | mission-listener·fallback-controller 배포 |
| `05_build_images.sh` | SPA 및 컨테이너 이미지 빌드(`PLATFORM`으로 멀티아키) |
| `06_push_images.sh` | 로컬 빌드 이미지 레지스트리 푸시 |
| `07_status.sh` | 노드·Pod·서비스·허브 헬스(`/api/health`)·Redis 키 현황 |
| `08_logs.sh` | 서비스별 로그 조회(`08_logs.sh hub\|edge\|robot\|rssi\|handover\|fallback`) |
| `11_run_webui.sh` | 웹 UI(허브 API + SPA) 실행 |
| `09_test_pipeline.sh` | accept/reject 조건 매칭 파이프라인 테스트 |
| `10_e2e_robot_test.sh` | 실제 로봇 대상 종단 간(E2E) 테스트 |
| `12_debug_webui_mission.sh` | 미션 배포 경로 단계별 디버깅 |
| `13_test_handover.sh` | RSSI 기반 핸드오버 시나리오 테스트 |
| `submit_mission.sh` | JSON 미션 문서를 노드 라벨/이름으로 타깃팅해 허브에 제출 |
| `99_cleanup.sh` | 배포 리소스 정리 |
| `run_all.sh` | `00`~`04` + `07`을 한 번에 실행 |

## 미션 제출 (JSON 문서)

UI 없이 JSON 문서로 미션을 정의하고 **노드 라벨**로 타깃팅해 배포할 수 있습니다.
문서 형식과 사용법은 [`missions/README.md`](missions/README.md) 참조.

```bash
# 노드 라벨의 노드들로 타깃팅 (라벨 → 노드명 자동 해석)
bash scripts/submit_mission.sh missions/example.mission.json --node-label node-role=edge
# 노드/기지국 이름 직접 지정
bash scripts/submit_mission.sh missions/example.mission.json --stations pi3,pi4
```

### 프런트엔드 (선택)

대시보드 UI는 `ui` 브랜치로 분리되어 있으며 부가 기능입니다. UI 없이도 허브 API
(`/api/*`)로 관제가 가능합니다. UI를 함께 서빙하려면 `ui` 브랜치에서 빌드한
`ui-spa/dist`를 허브의 `ui-spa/dist` 경로에 배치하세요. 없으면 허브는 안내 페이지를
반환합니다.

## Mock 모드

실제 장비 없이도 import와 기본 동작을 확인할 수 있습니다. 중앙 허브와 각 서비스는
`MOCK_MODE=1`에서 외부 MQTT/Redis/장비 연결 없이 동작합니다.

```bash
MOCK_MODE=1 DEV=1 bash scripts/11_run_webui.sh
```

## 검증

로컬에서 확인한 항목:

- Python/YAML/Shell 문법 검사
- Mock 모드 import smoke test
- `kubectl --dry-run=client`
- 로컬 Mosquitto publish/subscribe smoke test
- `npm run build` (프런트엔드)

## 공개 범위 주의

- 비공개 설정값은 `config.yaml`에 두고, 저장소에는 `config.example.yaml`만 둡니다.
- `.venv`, 빌드 산출물, Mosquitto 데이터, 로컬 로그는 커밋하지 않습니다.
- 노드 이름, MQTT 호스트, 장비 식별자, 비밀번호는 공개용 예시 값으로 바꿔 둡니다.
- 실제 배포 시 `deploy/*`와 `config.yaml` 값을 환경에 맞게 조정하세요.
