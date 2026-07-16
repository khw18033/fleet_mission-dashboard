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
| `99_cleanup.sh` | 배포 리소스 정리 |
| `run_all.sh` | `00`~`04` + `07`을 한 번에 실행 |

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
