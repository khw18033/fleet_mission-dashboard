# Robot Control Protocol (v1)

플랫폼(k3s/관리자)과 로봇 제어 어댑터 사이의 **SDK 독립 계약**입니다.
플랫폼은 이 프로토콜과 노드만 관리하고, 로봇 담당자는 이 계약을 지키는 어댑터를
자유로운 언어·SDK·베이스 이미지로 Docker에 담아 배포합니다.

- 전송 매체: **Redis** (단일 인스턴스, 로봇/기지국이 접근 가능한 주소)
- 인코딩: 모든 값은 **UTF-8 JSON 문자열**
- 키 네임스페이스: 로봇 시리얼번호(`SN`) 단위 — `robot:{SN}:*`
- 프로토콜 버전: `1` (`_meta.schema` 로 표기)

로봇 어댑터가 의존하는 것은 **Redis 클라이언트 하나뿐**입니다. robomaster·ROS 등
특정 SDK는 어댑터 컨테이너 내부에만 존재하며 플랫폼은 알 필요가 없습니다.

---

## 채널 요약

| 방향 | 채널 | Redis 타입 | 키 |
| --- | --- | --- | --- |
| 플랫폼 → 로봇 | 명령 | LIST | `robot:{SN}:commands` |
| 로봇 → 플랫폼 | 명령 결과(ack) | LIST | `robot:{SN}:cmd_result` |
| 로봇 → 플랫폼 | 텔레메트리 | HASH | `robot:{SN}:status` |
| 로봇 → 플랫폼 | 생존 신호 | STRING(TTL) | `robot:{SN}:online` |
| 로봇 → 플랫폼 | 이벤트 | PUB/SUB | `robot:{SN}:event:{type}` |

---

## 1. 명령 (플랫폼 → 로봇)

- 키: `robot:{SN}:commands` (LIST)
- 생산자: `RPUSH` (꼬리에 추가) — **FIFO 보장**
- 소비자: `BLPOP` (머리에서 대기·소비)

명령 페이로드:

```json
{
  "id": "mission-1737000000000:2",
  "target": "chassis",
  "action": "MOVE",
  "params": { "x": 1.0, "y": 0.0, "speed": 0.5 }
}
```

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `id` | string | 권장 | 명령 식별자. 결과(ack) 상관관계용. 보통 `{mission_id}:{step}` |
| `target` | string | 필수 | 제어 대상 (예: `chassis`, `actuator`, `led`, `flow`) |
| `action` | string | 필수 | 동작 (예: `MOVE`, `ROTATE`, `STOP`) |
| `params` | object | 선택 | 동작 파라미터. 로봇별 자유 |

`target`/`action`/`params`의 **의미는 로봇 종류마다 다릅니다**. 어떤 조합이 유효한지는
로봇 어댑터가 정의하며, 미션 빌더는 대상 로봇의 액션 문법을 참조합니다. 어댑터는
알 수 없는 `target`/`action`을 받으면 무시하지 말고 결과 채널에 `status: "error"`로
보고해야 합니다.

## 2. 명령 결과 / ACK (로봇 → 플랫폼)

- 키: `robot:{SN}:cmd_result` (LIST)
- 생산자(어댑터): 명령 처리 완료 후 `RPUSH`, 최근 N건만 유지(`LTRIM 0 N-1`)
- 소비자(플랫폼): 선택적. `LRANGE` 로 조회

결과 페이로드:

```json
{
  "id": "mission-1737000000000:2",
  "target": "chassis",
  "action": "MOVE",
  "status": "ok",
  "error": null,
  "ts": 1737000000.12
}
```

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | string | 대응하는 명령의 `id` (없으면 빈 문자열) |
| `status` | string | `ok` \| `error` |
| `error` | string/null | 실패 사유 (성공 시 null) |
| `ts` | number | 처리 완료 epoch 초 |

## 3. 텔레메트리 (로봇 → 플랫폼) — 확장 필드 규약

- 키: `robot:{SN}:status` (HASH), 각 필드 값은 JSON, 해시 전체 TTL 유지
- **핵심 필드(core)** 는 소비자가 이름으로 신뢰할 수 있습니다. 그 외 필드는 모두
  **확장(extension)** 이며, 소비자는 고정된 필드 집합을 가정하지 않고 존재하는 필드를
  그대로 통과(pass-through)시켜야 합니다.

핵심 필드(권장 최소 집합):

| 필드 | 값 스키마 | 설명 |
| --- | --- | --- |
| `battery` | `{ "soc": <int 0-100> }` | 배터리 잔량(%) |
| `_meta` | `{ "robot_type": <str>, "schema": 1, "ts": <num> }` | 어댑터 메타데이터 |

확장 필드(EP01 예시 — 다른 로봇은 자유롭게 다른 필드 사용):

| 필드 | 값 스키마(예) |
| --- | --- |
| `position` | `{ "x", "y" }` |
| `speed` | `{ "speed", "vx", "vy" }` |
| `imu` | `{ "ax", "ay", "az" }` |
| `esc_rpm` | `{ "wheels": [...] }` |
| `armor` | `{ "id", "type", "position", "ts" }` |

플랫폼(대시보드)은 `battery`·`_meta` 를 핵심으로 처리하고, 나머지 모든 필드는
`telemetry` 딕셔너리로 그대로 노출합니다. 따라서 **로봇이 새 필드를 추가해도 플랫폼
코드 변경 없이** 전달·표시됩니다.

## 4. 생존 신호 (로봇 → 플랫폼)

- 키: `robot:{SN}:online` (STRING, TTL)
- 어댑터가 `SET robot:{SN}:online 1 EX <offline_timeout>` 를 주기적으로 갱신
- 키 존재 = 온라인. TTL 만료 = 오프라인. 종료 시 키 삭제 권장.

## 5. 이벤트 (로봇 → 플랫폼)

- 채널: `robot:{SN}:event:{type}` (PUB/SUB)
- 즉시성이 필요한 비동기 이벤트(예: `armor_hit`)를 `PUBLISH`
- 동일 데이터를 텔레메트리 해시에도 기록해 폴링 소비자를 지원할 수 있음

---

## 책임 경계

| | 플랫폼(k3s/관리자) | 로봇 어댑터(로봇 담당) |
| --- | --- | --- |
| 소유 | central-hub, broadcaster, listener, redis, MQTT, 노드/DaemonSet | `robot:{SN}:commands` 소비 + `status`/`online`/`cmd_result`/`event` 생산 |
| SDK | 로봇 SDK 불필요 | 자유(robomaster/ROS/...) — 컨테이너 내부에만 존재 |
| 배포 | 노드 라벨 + DaemonSet 스케줄로 어댑터 이미지 선택 | 자기 베이스 이미지/의존성으로 빌드 |
| 설정 | ConfigMap/env로 주입 | `REDIS_HOST`, `ROBOT_SN` 등 env만 필요(플랫폼 config 불필요) |

어댑터가 반드시 지킬 것:
1. `robot:{SN}:commands` 를 `BLPOP` 로 소비하고, 각 명령마다 `cmd_result` 로 ack.
2. `battery`·`_meta` 를 포함한 텔레메트리를 `status` 해시에 기록.
3. `online` 키를 TTL로 갱신.
4. 플랫폼 config.yaml 에 의존하지 않고 env(`REDIS_HOST`/`ROBOT_SN`)만으로 동작.

참조 구현: [`apps/brain-ep01/link/link_proxy.py`](../apps/brain-ep01/link/link_proxy.py) (EP01/robomaster).
기계 판독용 스키마: [`schemas.json`](schemas.json).
