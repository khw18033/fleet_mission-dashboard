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

## k3s 없이 실물 로봇 명령 전달 테스트 (pi5 + 로봇만)

**k3s·허브·MQTT 없이**, 이 브랜치의 `link_text_proxy.py`(표준 라이브러리만)와
제어용 라즈베리파이(예: pi5) + 로봇만으로 명령 전달을 검증할 수 있습니다.
robomaster 파이썬 SDK도 필요 없습니다(평문 TCP SDK, 포트 40923 사용).

### 준비 (제어 RPi에서)

1. RoboMaster를 **AP 모드**로 켜면 자체 Wi-Fi `RMEP-xxxxxx`가 뜨고, 접속 시 로봇 IP는
   고정 `192.168.2.1`입니다. USB Wi-Fi(예: ipTIME)를 로봇 전용으로 붙여 접속하세요:

   ```bash
   nmcli dev wifi connect RMEP-xxxxxx password <AP비밀번호>   # config.yaml robot.ap.password
   ping -c2 192.168.2.1                                       # 로봇 응답 확인
   ```

   (내장 Wi-Fi/이더넷은 그대로 두면 기존 네트워크가 유지됩니다.)

2. 이 파일을 RPi로 복사: `scp apps/brain-ep01/link/link_text_proxy.py <rpi>:/tmp/`

### 방법 A — Redis 없이 직접 실행 (`--exec`)

명령(JSON 1개 또는 배열)을 곧바로 로봇에 전달합니다. 가장 간단한 확인 방법입니다.

```bash
# LED 초록
python3 /tmp/link_text_proxy.py --exec '{"target":"led","action":"SET","params":{"r":0,"g":255,"b":0}}'

# 전진 0.3m 후 LED 초록 (배열, delay_sec 지원)
python3 /tmp/link_text_proxy.py --exec '[
  {"target":"chassis","action":"MOVE","params":{"x":0.3,"y":0,"speed":0.3},"delay_sec":3},
  {"target":"led","action":"SET","params":{"r":0,"g":255,"b":0}}
]'
```

지원 명령: `chassis`(MOVE/ROTATE/STOP), `led`(SET), `actuator`(GRIPPER/ARM_MOVE).

### 방법 B — 프로토콜 그대로(Redis 명령 큐)

실제 계약(`robot:{SN}:commands` 소비 → `cmd_result`/`status`/`online` 기록)을 검증하려면
Redis가 하나 필요합니다. RPi에 설치하거나(`sudo apt install redis-server`) 접근 가능한
아무 Redis를 쓰면 됩니다.

```bash
# 1) 어댑터 실행 (RPi)
REDIS_HOST=127.0.0.1 ROBOT_SN=ep01-test ROBOT_IP=192.168.2.1 \
  python3 /tmp/link_text_proxy.py

# 2) 다른 셸에서 명령 주입 + 결과 확인
redis-cli RPUSH robot:ep01-test:commands \
  '{"id":"t1","target":"led","action":"SET","params":{"r":0,"g":0,"b":255}}'
redis-cli GET   robot:ep01-test:online          # "1"
redis-cli HGET  robot:ep01-test:status _meta    # {"robot_type":"ep01","schema":1,...}
redis-cli LRANGE robot:ep01-test:cmd_result 0 -1  # {"id":"t1","status":"ok",...}
```

`redis-cli`가 없으면 파일 내 `MiniRedis`(표준 라이브러리 RESP 클라이언트)로도 주입할 수
있습니다. 실검증: 실물 EP01(`RMEP-36ceb5`) + pi5(ipTIME `wlan1`)에서 LED·이동을 A/B 두
방식 모두 확인했습니다.
