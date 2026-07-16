# Fleet Mission — UI (대시보드, 부가 기능)

Fleet Mission 시스템의 **대시보드 프런트엔드**입니다. Vite + React SPA로,
대시보드·미션 빌더·MQTT 로그·Config 화면을 제공합니다.

> 이 브랜치는 모노레포를 책임별로 분리한 `ui` 브랜치이며 **부가 기능**입니다.
> UI 없이도 플랫폼(`admin` 브랜치)의 허브 API(`/api/*`)만으로 관제가 가능합니다.
> 로봇 제어 어댑터는 `robot-image` 브랜치를 참조하세요.

## 구성

| 경로 | 설명 |
| --- | --- |
| `ui-spa/` | Vite + React 프런트엔드 소스 |
| `ui-spa/src/pages/Dashboard.tsx` | 노드/로봇/RSSI/핸드오버/미션 대시보드 |
| `ui-spa/src/pages/MissionBuilder.tsx` | 드래그 기반 미션 빌더 |
| `ui-spa/src/pages/Config.tsx` | 시스템 상태·Redis 조회·배포 순서 |
| `protocol/` | 허브 API가 노출하는 로봇 텔레메트리 계약(참조) |

## 개발

```bash
cd ui-spa
npm install
npm run dev        # Vite 개발 서버(:5173), API는 VITE_API_TARGET로 프록시
```

`VITE_API_TARGET`(기본 `http://127.0.0.1:5001`)로 `admin` 브랜치의 허브 API를 가리킵니다.

## 빌드

```bash
cd ui-spa
npm run build      # 산출물: ui-spa/dist
```

빌드된 `ui-spa/dist`를 `admin` 브랜치 허브의 `ui-spa/dist` 경로에 배치하면 허브가
정적 파일로 서빙합니다.

## 데이터 계약

대시보드는 허브의 `/api/dashboard`(및 `/ws/dashboard`)를 소비합니다. 로봇 텔레메트리는
[확장 필드 규약](protocol/PROTOCOL.md)을 따르며, `robot.telemetry` 딕셔너리로 임의의
확장 필드가 전달되므로 로봇 종류가 늘어도 UI는 존재하는 필드만 렌더링합니다.

미션 빌더는 허브의 `/api/mission-spec`(배포된 로봇의 액션 문법)을 불러와, 그 배포가
지원하는 블록만 팔레트에 노출합니다. 스펙을 받지 못하면(standalone) 전체 팔레트를
표시합니다. 즉 로봇 종류가 바뀌면 허브 config의 `mission_spec`만 교체하면 됩니다.
