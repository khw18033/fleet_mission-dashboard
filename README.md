# Fleet Mission Dashboard

플릿 미션 대시보드와 로봇/엣지 제어를 묶은 통합 시스템입니다.

## 구성
- `apps/central-hub`: FastAPI 기반 중앙 허브, MQTT/Redis 연동, 웹 UI 서빙
- `services/*`: 미션 수신, 브로드캐스트, 핸드오버, RSSI 수집, fallback 제어
- `apps/brain-ep01/*`: EP01 로봇용 링크/작업 워커
- `deploy/*`: k3s 배포용 Kubernetes 매니페스트와 ConfigMap
- `ui-spa`: Vite + React 프런트엔드
- `scripts/*`: 배포, 점검, 테스트, 정리용 셸 스크립트

## 시작하기
1. `config.example.yaml`을 복사해 `config.yaml`을 만듭니다.
2. MQTT, LLM, k3s 노드 이름 등 로컬 환경 값으로 수정합니다.
3. 필요한 패키지와 도구를 설치합니다.

```bash
cp config.example.yaml config.yaml
bash scripts/00_check_prereqs.sh
```

## 실행
### 웹 UI
```bash
bash scripts/11_run_webui.sh
```

개발 모드:
```bash
DEV=1 bash scripts/11_run_webui.sh
```

### 전체 배포
```bash
bash scripts/run_all.sh
```

## Mock 모드
실제 장비 없이도 import/기본 동작을 확인할 수 있습니다.

```bash
MOCK_MODE=1 DEV=1 bash scripts/11_run_webui.sh
```

## 안전한 공개 범위
- 비공개 설정값은 `config.yaml`에 두고, 저장소에는 `config.example.yaml`만 둡니다.
- `.venv`, 빌드 산출물, Mosquitto 데이터, 로컬 로그는 커밋하지 않습니다.
- 노드 이름, MQTT 호스트, 장비 식별자는 공개용 예시 값으로 바꿔 두었습니다.

## 검증
로컬에서 확인한 항목:
- Python/YAML/Shell 문법 검사
- Mock 모드 import smoke test
- `kubectl --dry-run=client`
- 로컬 Mosquitto publish/subscribe smoke test

## 프런트엔드
```bash
cd ui-spa
npm install
npm run build
```

## 참고
- 중앙 허브와 서비스들은 `MOCK_MODE=1`에서 외부 MQTT/Redis/장비 연결 없이 import 가능합니다.
- 실제 배포 시에는 `deploy/*`와 `config.yaml` 값을 환경에 맞게 조정하세요.