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

    def get(self, key):
        return self._strings.get(key)

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    def publish(self, channel, payload):
        return 1

class VisionWorker:
    def __init__(self):
        self.r = MockRedis() if MOCK_MODE else redis.Redis(host=os.getenv("REDIS_HOST", cfg.get("network.redis_host", "redis-service")), port=int(os.getenv("REDIS_PORT", cfg.get("network.redis_port", 6379))), decode_responses=True)
        self.robot_id = os.getenv("ROBOT_SN", cfg.get("runtime.default_robot_sn", "ep01"))
        self.task_id = os.getenv("TASK_ID", cfg.get("runtime.default_vision_task_id", "default_vision"))
        self.processing_interval = float(cfg.get("tasks.defaults.vision.processing_interval_sec", 0.2))
        
    def run(self):
        print(f"[*] Vision Worker ({self.task_id}) active for {self.robot_id}")
        if MOCK_MODE:
            print("[mock] Vision worker skipped")
            return
        
        # 1. LLM이 정의한 파라미터 가져오기 (예: "target": "person")
        task_config = json.loads(self.r.get(f"task_config:{self.task_id}") or "{}")
        target_object = task_config.get("target", "person")

        while True:
            # Link Proxy가 Redis Hash에 쓴 'raw_vision' 데이터를 가져옴
            raw_img = self.r.hget(f"robot:{self.robot_id}:status", "raw_vision")
            
            if raw_img:
                # [AI 로직] target_object가 감지되었는지 판별
                detected = self.detect_logic(raw_img, target_object)
                
                if detected:
                    # 이벤트 발생 알림 (LLM이 설정한 다음 단계 트리거)
                    event_data = {"event": "object_detected", "target": target_object, "time": time.time()}
                    self.r.publish(f"event:{self.robot_id}:logic", json.dumps(event_data))
                    print(f"[!] {target_object} Detected! Event published.")
            
            time.sleep(self.processing_interval)

    def detect_logic(self, img, target):
        # 실제로는 OpenCV/YOLO 모델이 들어가는 자리
        return True # 시뮬레이션을 위해 항상 감지된 것으로 가정

if __name__ == "__main__":
    VisionWorker().run()