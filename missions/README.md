# 미션 문서 (JSON)

UI 없이 **JSON 문서로 미션을 정의**하고, **노드 라벨** 또는 노드/기지국 이름으로
타깃팅해 허브에 제출합니다. 제출은 [`scripts/submit_mission.sh`](../scripts/submit_mission.sh)로 합니다.

## 문서 형식

```json
{
  "mission_name": "patrol-01",
  "conditions": { "robot_type": "ep01", "robot_online": true, "min_battery": 20, "max_latency_ms": 9999 },
  "target_stations": [],
  "nodes": [
    { "target": "chassis", "action": "MOVE", "params": { "x": 1.0, "y": 0.0, "speed": 0.5 }, "delay_sec": 1 }
  ]
}
```

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `mission_name` | 선택 | 미션 이름 (생략 시 자동 생성) |
| `conditions` | 선택 | 로봇이 수락 판정에 쓰는 조건 (robot_type/robot_online/min_battery/max_latency_ms) |
| `target_stations` | 선택 | 타깃 노드/기지국 이름. 스크립트 옵션으로 덮어쓸 수 있음. 비우면 전체 브로드캐스트 |
| `nodes` | 필수 | 실행할 명령 노드 배열. 각 노드는 `{target, action, params, delay_sec}` |

`nodes`의 `target`/`action`은 대상 로봇의 액션 문법(허브 `/api/mission-spec`,
즉 config의 `mission_spec`)을 따릅니다. `flow`(REPEAT/IF/WAIT_EVENT)로 반복·분기·이벤트
대기도 표현할 수 있습니다.

## 제출

```bash
# 노드 라벨로 타깃팅 (라벨 → 노드명 자동 해석)
bash scripts/submit_mission.sh missions/example.mission.json --node-label node-role=robot

# 노드/기지국 이름 직접 지정
bash scripts/submit_mission.sh missions/example.mission.json --stations pi3,pi4

# 문서의 target_stations 그대로 사용
bash scripts/submit_mission.sh missions/example.mission.json

# 로컬 허브로 제출
HUB_URL=http://localhost:5001 bash scripts/submit_mission.sh missions/example.mission.json
```

노드 라벨은 `kubectl get nodes -l KEY=VAL` 로 노드 이름을 해석해 `target_stations`에
채웁니다. 기지국 broadcaster는 자신의 `STATION_ID`(= 노드 이름)가 타깃에 포함될 때만
미션을 브로드캐스트하므로, 라벨로 지정한 노드들에만 미션이 배포됩니다.
