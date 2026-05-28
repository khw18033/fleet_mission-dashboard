import redis
import json
import os
import time
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.config_loader import load_config
cfg = load_config()
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"


class MockRedis:
    def __init__(self):
        self._strings = {}
        self._hashes = {}
        self._lists = {}

    def get(self, key):
        return self._strings.get(key)

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    def rpush(self, key, value):
        self._lists.setdefault(key, []).append(value)

    def publish(self, channel, payload):
        return 1

class NavWorker:
    def __init__(self):
        # Redis 연결 설정
        self.r = MockRedis() if MOCK_MODE else redis.Redis(
            host=os.getenv("REDIS_HOST", cfg.get("network.redis_host", "redis-service")), 
            port=int(os.getenv("REDIS_PORT", cfg.get("network.redis_port", 6379))), 
            decode_responses=True
        )
        self.robot_id = os.getenv("ROBOT_SN", cfg.get("runtime.default_robot_sn", "ep01"))
        self.task_id = os.getenv("TASK_ID", cfg.get("runtime.default_task_id", "nav_task_01"))
        self.arrival_threshold = float(cfg.get("tasks.defaults.navigation.arrival_threshold_m", 0.1))
        self.check_interval = float(cfg.get("tasks.defaults.navigation.position_check_interval_sec", 0.5))
        
    def run(self):
        print(f"[*] Navigation Worker ({self.task_id}) started for {self.robot_id}")
        if MOCK_MODE:
            print("[mock] Navigation worker skipped")
            return
        
        # 1. LLM이 설정한 Task 정보 읽기 (예: {"target_x": 1.5, "target_y": 0.5})
        task_config = json.loads(self.r.get(f"task_config:{self.task_id}") or "{}")
        tx = task_config.get("target_x", 0)
        ty = task_config.get("target_y", 0)

        default_speed = float(cfg.get("tasks.defaults.navigation.speed", 0.5))
        move_cmd = {
            "target": "chassis",
            "action": "MOVE",
            "params": {"x": tx, "y": ty, "z": 0, "spd": default_speed}
        }
        self.r.rpush(f"robot:{self.robot_id}:commands", json.dumps(move_cmd))
        print(f"[>] Move command sent: x={tx}, y={ty}")

        # 3. 도착 여부 모니터링 (Feedback Loop)
        while True:
            # Link Proxy가 업데이트하는 현재 좌표 읽기
            pos_data = self.r.hget(f"robot:{self.robot_id}:status", "position")
            if pos_data:
                pos = json.loads(pos_data)
                curr_x, curr_y = pos.get('x', 0), pos.get('y', 0)
                
                # 거리 계산 (간단한 유클리드 거리)
                distance = ((tx - curr_x)**2 + (ty - curr_y)**2)**0.5
                
                if distance < self.arrival_threshold: # 임계값 이내 도착 시
                    print(f"[!] Target Reached: ({curr_x}, {curr_y})")
                    # LLM 오케스트레이터에게 완료 이벤트 알림
                    self.r.publish(f"event:{self.robot_id}:logic", json.dumps({
                        "event": "nav_completed",
                        "task_id": self.task_id,
                        "final_pos": [curr_x, curr_y]
                    }))
                    break
            
            time.sleep(self.check_interval)

if __name__ == "__main__":
    NavWorker().run()