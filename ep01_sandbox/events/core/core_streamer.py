import time
import math
import json
import sys
from robomaster import robot

class CoreStreamer:
    def __init__(self):
        # 상태 관리를 위한 변수 (X, Y 위치 및 배터리 변화 추적)
        self.last_battery = None
        self.last_pos = [0.0, 0.0] 
        
    def _emit(self, category, tag, data):
        """
        [데이터 송신부] 
        JSON 형식으로 표준 출력(stdout). K3s 파이프라인의 입구 역할을 합니다.
        """
        payload = {
            "timestamp": round(time.time(), 3),
            "source": "core_streamer",
            "category": category,
            "tag": tag,
            "data": data
        }
        # 즉시 전송을 위해 flush=True
        print(json.dumps(payload), flush=True)

    def sub_armor_event(self, armor_info):
        """아머 타격 이벤트"""
        armor_id, hit_type = armor_info
        self._emit("event", "armor_hit", {
            "id": armor_id,
            "type": hit_type
        })

    def sub_battery_info(self, info):
        """배터리 잔량 업데이트"""
        if info != self.last_battery:
            self._emit("status", "battery", {"soc": info})
            self.last_battery = info

    def sub_position_info(self, pos_info):
        """위치 데이터 (유니티 좌표 동기화용)"""
        x, y, _ = pos_info
        dist = math.sqrt((x - self.last_pos[0])**2 + (y - self.last_pos[1])**2)
        # 2cm 이상 유의미한 이동 시에만 스트리밍
        if dist > 0.02:
            self._emit("stream", "position", {
                "x": round(x, 3), 
                "y": round(y, 3)
            })
            self.last_pos = [x, y]

    def sub_velocity_info(self, vel_info):
        """실시간 속도 데이터"""
        vgx, vgy = vel_info[:2]
        speed = math.sqrt(vgx**2 + vgy**2)
        if speed > 0.05:
            self._emit("stream", "velocity", {
                "speed": round(speed, 2),
                "vx": round(vgx, 2),
                "vy": round(vgy, 2)
            })

    def sub_imu_info(self, imu_info):
        """3축 가속도 (그라파나 분석용)"""
        acc = [round(v, 3) for v in imu_info[0:3]]
        self._emit("raw", "imu_acc", {
            "ax": acc[0], 
            "ay": acc[1], 
            "az": acc[2]
        })

    def sub_esc_info(self, esc_info):
        """모터 RPM (유니티 바퀴 회전 연동)"""
        rpms = [m[0] for m in esc_info]
        if any(abs(r) > 5 for r in rpms):
            self._emit("raw", "esc_rpm", {"wheels": rpms})

def core_streamer():
    collector = CoreStreamer()
    ep_robot = robot.Robot()
    
    try:
        if not ep_robot.initialize(conn_type="sta"):
            err_msg = {"timestamp": time.time(), "category": "error", "message": "Robot init failed"}
            print(json.dumps(err_msg), file=sys.stderr)
            return

        # [구독 정책]
        ep_robot.armor.sub_hit_event(callback=collector.sub_armor_event)
        ep_robot.battery.sub_battery_info(freq=1, callback=collector.sub_battery_info)
        ep_robot.chassis.sub_position(freq=5, callback=collector.sub_position_info)
        ep_robot.chassis.sub_velocity(freq=5, callback=collector.sub_velocity_info)
        ep_robot.chassis.sub_imu(freq=2, callback=collector.sub_imu_info)
        ep_robot.chassis.sub_esc(freq=2, callback=collector.sub_esc_info)

        # 시스템 시작 알림
        collector._emit("system", "status", {"message": "Core Streamer Active"})

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        collector._emit("system", "status", {"message": "Stopped by User"})
    except Exception as e:
        err_log = {"category": "error", "message": str(e)}
        print(json.dumps(err_log), file=sys.stderr)
    finally:
        ep_robot.close()

if __name__ == "__main__":
    core_streamer()