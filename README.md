# Fleet Mission Dashboard

여러 대의 로봇과 기지국(엣지)을 관제하는 통합 시스템입니다. 중앙 허브가 미션을
브로드캐스트하면 기지국이 중계하고, 각 로봇의 제어 노드가 조건을 평가해 수락/거절한 뒤
실행합니다. RSSI 기반 기지국 핸드오버와 서버 단절 시 자동 fallback을 지원합니다.

이 저장소는 **책임별로 브랜치를 분리**해 관리합니다. `main`은 개요만 두고, 실제 코드는
아래 세 브랜치에 있습니다.

## 브랜치 구조

| 브랜치 | 책임 | 내용 |
| --- | --- | --- |
| [`admin`](../../tree/admin) | 플랫폼/관리자 | 중앙 허브, 기지국·로봇 서비스, k3s 배포 매니페스트, 운영 스크립트, 제어 프로토콜. 관리자는 프로토콜과 노드만 관리 |
| [`robot-image`](../../tree/robot-image) | 로봇 어댑터 | 로봇별 실제 SDK와 제어 명령 실행 어댑터(EP01 link_proxy, 작업 워커). 프로토콜만 지키면 자유 SDK로 구현 |
| [`ui`](../../tree/ui) | UI (부가) | Vite + React 대시보드. UI 없이도 허브 API로 관제 가능 |

## 아키텍처 핵심

제어 명령은 특정 SDK가 아니라 **SDK 독립 Redis 프로토콜**로 정의됩니다. 덕분에
플랫폼(k3s) 담당과 로봇 담당의 책임을 깨끗이 분리할 수 있습니다.

- 플랫폼(`admin`)은 미션 분배·조건 평가·핸드오버·대시보드 API를 담당하며 로봇 SDK를
  전혀 알 필요가 없습니다.
- 로봇 담당(`robot-image`)은 프로토콜을 구현하는 어댑터를 자유로운 언어·SDK·베이스
  이미지로 Docker에 담아 배포합니다.
- 배포 시 k3s가 노드 라벨과 DaemonSet으로 각 노드에 맞는 어댑터 이미지를 스케줄합니다.

제어 프로토콜(명령/텔레메트리/ack/생존 신호/이벤트)의 상세 계약은 `admin`·`robot-image`
브랜치의 [`protocol/PROTOCOL.md`](../../blob/admin/protocol/PROTOCOL.md)에 정의되어 있습니다.

## 메시지 흐름

```
[중앙 허브] --fleet/mission/deploy--> [기지국 broadcaster]
                                        --fleet/mission/broadcast--> [로봇 listener]
[로봇 listener] --fleet/mission/accept/{station}--> [broadcaster]
                                        --fleet/mission/accepted--> [중앙 허브]

명령 실행(SDK 독립 Redis 프로토콜):
[listener] --RPUSH robot:{SN}:commands--> [robot-image 어댑터] --BLPOP-->
[어댑터] --robot:{SN}:status / :online / :cmd_result--> [허브/대시보드]
```

## 시작하기

원하는 책임의 브랜치를 체크아웃해 사용하세요.

```bash
git checkout admin         # 플랫폼/배포/운영
git checkout robot-image   # 로봇 제어 어댑터
git checkout ui            # 대시보드
```
