# Phase 2 적용 요약

## 주요 서비스 및 기능

- **RSSI Collector**: 각 로봇/엣지에서 RSSI 신호 수집, Redis 저장, Prometheus 메트릭 노출
- **Handover Controller**: RSSI 기반 핸드오버 로직, Active/Standby 상태 관리, Prewarm/히스테리시스 적용
- **Local Fallback Controller**: 중앙 장애 시 last-mission.json 캐시 활용, 재연결 시 자동 복구
- **로봇 상태 관리**: heartbeat 기반 offline 감지, Redis 동기화, UI 반영
- **Config/매핑 테이블**: SSID-SN 매핑 등 구조화

## 폴더 구조
- services/rssi_collector/
- services/handover_controller/
- services/fallback_controller/
- central-hub/robot_heartbeat.py
- config/robot_mapping.yaml

## 운영 방법
- 각 서비스별 Dockerfile/requirements.txt 참고
- central-hub/robot_heartbeat.py를 주기적으로 실행하여 offline 감지

## TODO
- 실제 환경에 맞는 RSSI/wlan/mission 연동 코드로 교체 필요
- UI에서 Redis의 online 상태를 반영하도록 연동 확인
