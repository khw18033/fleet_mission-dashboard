import time
import json
import cv2
import os
import sys
from robomaster import robot

class VisionStreamer:
    def __init__(self):
        # 최신 데이터를 보관 (유니티 동기화 및 스냅샷 참조용)
        self.latest_data = {
            "marker": {"id": None, "size": 0, "pos": [0, 0]},
            "line": {"x": 0.5, "angle": 0}
        }
        # 분석용 스냅샷 저장 경로 (라즈베리파이 공유 볼륨 등을 고려)
        self.snapshot_path = "/tmp/vision_snapshot.jpg"

    def _emit(self, tag, data):
        """
        JSON 출력: K3s 로그 수집기 및 엣지 클라우드 파이프라인용
        """
        payload = {
            "timestamp": round(time.time(), 3),
            "source": "vision_streamer",
            "category": "vision",
            "tag": tag,
            "data": data
        }
        print(json.dumps(payload), flush=True)

    def on_detect_marker(self, info):
        """마커 감지 콜백: ID, 크기, 좌표 추출"""
        if info:
            # info 내부: [[x, y, w, h, marker_id], ...]
            x, y, w, h, m_id = info[0]
            self.latest_data["marker"] = {
                "id": m_id,
                "size": round(w * h, 4), # 마커가 차지하는 면적 (거리 짐작용)
                "pos": [round(x, 3), round(y, 3)]
            }
            self._emit("marker", self.latest_data["marker"])

    def on_detect_line(self, info):
        """라인 감지 콜백: 중앙점 오차 및 각도 추출"""
        if info and len(info) > 1:
            # info[1] 구성: [x, y, curvature, angle]
            line_info = info[1]
            self.latest_data["line"] = {
                "x": round(line_info[0], 3),
                "angle": round(line_info[3], 2)
            }
            self._emit("line", self.latest_data["line"])

    def run(self):
        ep_robot = robot.Robot()
        
        # 로봇 초기화 (스테이션 모드 연결)
        if not ep_robot.initialize(conn_type="sta"):
            err = {"category": "error", "message": "Vision Streamer: Robot init failed"}
            print(json.dumps(err), file=sys.stderr)
            return

        try:
            # 1. 시각 분석 엔진 및 카메라 스트림 가동
            ep_robot.camera.start_video_stream(display=False)
            
            # 마커 감지 구독 (AI 모듈 활성화)
            ep_robot.vision.sub_detect_info(name="marker", callback=self.on_detect_marker)
            
            # 라인 감지 구독 (파란색 라인 기준)
            ep_robot.vision.sub_detect_info(name="line", color="blue", callback=self.on_detect_line)

            # 시스템 시작 로그
            self._emit("system", {"status": "active", "message": "Vision Streamer Started"})

            last_capture_time = 0
            while True:
                # 2. 실시간 스냅샷 저장 로직 (2초 간격)
                # 이 파일은 나중에 웹 대시보드에서 불러다 쓸 수 있습니다.
                current_time = time.time()
                if current_time - last_capture_time > 2.0:
                    img = ep_robot.camera.read_cv2_image(strategy="newest")
                    if img is not None:
                        cv2.imwrite(self.snapshot_path, img)
                        # 파일 경로 정보를 전송 (이미지 데이터 자체는 파일로 관리)
                        self._emit("snapshot", {"path": self.snapshot_path})
                        last_capture_time = current_time
                
                # CPU 점유율 방지를 위한 미세 대기
                time.sleep(0.1)

        except Exception as e:
            err_msg = {"category": "error", "message": str(e)}
            print(json.dumps(err_msg), file=sys.stderr)
        
        finally:
            # 리소스 해제
            ep_robot.vision.unsub_detect_info(name="marker")
            ep_robot.vision.unsub_detect_info(name="line")
            ep_robot.camera.stop_video_stream()
            ep_robot.close()
            self._emit("system", {"status": "inactive", "message": "Vision Streamer Stopped"})

if __name__ == "__main__":
    streamer = VisionStreamer()
    streamer.run()