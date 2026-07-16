# Fleet Mission — Robot Image (로봇 어댑터)

로봇에서 실제로 실행되는 **제어 어댑터**와 로봇별 SDK/작업 코드입니다.
[Robot Control Protocol](protocol/PROTOCOL.md)을 구현해 플랫폼(관리자)과
Redis 프로토콜로만 통신하며, robomaster 등 특정 SDK는 이 컨테이너 내부에만 존재합니다.

> 이 브랜치는 모노레포를 책임별로 분리한 `robot-image` 브랜치입니다.
> 플랫폼/관리 기능은 `admin`, 대시보드 UI는 `ui` 브랜치를 참조하세요.

## 구성

| 경로 | 설명 |
| --- | --- |
| `apps/brain-ep01/link/link_proxy.py` | EP01 제어 어댑터 — 명령 큐 소비 → robomaster SDK 호출 (Python 3.8) |
| `apps/brain-ep01/link/link_text_proxy.py` | EP01 경량 어댑터 — robomaster SDK 없이 평문 TCP SDK(40923)로 제어. **표준 라이브러리만** 사용해 Python 3.13/라즈베리파이에서 바로 실행(Redis도 내장 RESP 클라이언트) |
| `apps/brain-ep01/tasks/navigation` | 주행 작업 워커 |
| `apps/brain-ep01/tasks/vision` | 비전 작업 워커 |
| `ep01_sandbox` | EP01 이벤트/미션 실행 실험 코드 |
| `config/robot_mapping.yaml` | 로봇 SSID-SN 매핑 예시 |
| `protocol/` | 플랫폼과의 계약(프로토콜) 문서·스키마 |
| `tools/config_loader.py` | 설정 로더(파일 부재 시 env만으로 동작) |

## 프로토콜 요약 (자세히는 [protocol/PROTOCOL.md](protocol/PROTOCOL.md))

어댑터가 지켜야 할 Redis 계약 (로봇 SN 단위):

| 방향 | 채널 | 키 |
| --- | --- | --- |
| 명령 수신 | LIST(BLPOP) | `robot:{SN}:commands` |
| 명령 결과(ack) | LIST(RPUSH) | `robot:{SN}:cmd_result` |
| 텔레메트리 | HASH | `robot:{SN}:status` (핵심: `battery`,`_meta` + 확장 필드) |
| 생존 신호 | STRING(TTL) | `robot:{SN}:online` |
| 이벤트 | PUB/SUB | `robot:{SN}:event:{type}` |

## 새 로봇 종류 추가

1. `apps/brain-<type>/link/` 에 어댑터 구현: `robot:{SN}:commands`를 `BLPOP`으로 소비,
   `target/action/params`를 해당 로봇 SDK 호출로 번역.
2. `status`(battery/_meta + 자유 확장 필드)·`online`·`cmd_result`를 기록.
3. 자체 Dockerfile로 원하는 베이스 이미지/의존성으로 빌드.
4. 플랫폼 config.yaml에 의존하지 말 것 — `REDIS_HOST`, `ROBOT_SN` env만 사용.

## 빌드 (EP01 예시)

```bash
docker build -f apps/brain-ep01/link/Dockerfile -t <registry>/ep01-link:<tag> .
```

## 로컬 확인 (Mock)

```bash
MOCK_MODE=1 python apps/brain-ep01/link/link_proxy.py
```
