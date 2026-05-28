import argparse
import time
import sys
import json
from robomaster import robot

def low_executor():
    parser = argparse.ArgumentParser(description="RoboMaster Low-level Task Executor")
    parser.add_argument("--action", type=str, choices=["MOVE", "ROTATE", "ACTUATOR", "FEEDBACK"], required=True)
    
    # 1. 이동 관련 (속도 조절 가능)
    parser.add_argument("--x", type=float, default=0.0)
    parser.add_argument("--y", type=float, default=0.0)
    parser.add_argument("--speed", type=float, default=0.5)
    
    # 2. 회전 관련 (속도 조절 가능)
    parser.add_argument("--yaw", type=int, default=0)
    parser.add_argument("--v_speed", type=int, default=45)
    
    # 3. 로봇 팔 관련 (좌표만 전담)
    parser.add_argument("--arm_x", type=float, default=0.0)
    parser.add_argument("--arm_y", type=float, default=0.0)
    
    # 4. 집게 관련 (파워 조절 가능)
    parser.add_argument("--grip", type=str, choices=["open", "close", "none"], default="none")
    parser.add_argument("--grip_p", type=int, default=50)
    
    # 5. LED 관련
    parser.add_argument("--r", type=int, default=255)
    parser.add_argument("--g", type=int, default=255)
    parser.add_argument("--b", type=int, default=255)
    
    args = parser.parse_args()
    ep_robot = robot.Robot()

    def log_result(status, message):
        print(json.dumps({
            "timestamp": round(time.time(), 3),
            "source": "low_executor",
            "category": "executor",
            "status": status, 
            "message": message
        }), flush=True)

    try:
        if not ep_robot.initialize(conn_type="sta"):
            log_result("error", "Robot connection failed")
            return

        # --- MOVE: 섀시 이동 (속도 적용) ---
        if args.action == "MOVE":
            log_result("running", f"Moving to x:{args.x}, y:{args.y} at {args.speed}m/s")
            ep_robot.chassis.move(x=args.x, y=args.y, z=0, xy_speed=args.speed).wait_for_completed()

        # --- ROTATE: 섀시 회전 (속도 적용) ---
        elif args.action == "ROTATE":
            log_result("running", f"Rotating {args.yaw}deg at {args.v_speed}deg/s")
            ep_robot.chassis.move(x=0, y=0, z=args.yaw, z_speed=args.v_speed).wait_for_completed()

        # --- ACTUATOR: 로봇 팔(좌표) 및 집게(파워) ---
        elif args.action == "ACTUATOR":
            # 팔은 정석대로 x, y 좌표만 이동
            log_result("running", f"Arm move to x:{args.arm_x}, y:{args.arm_y}")
            ep_robot.robotic_arm.move(x=args.arm_x, y=args.arm_y).wait_for_completed()
            
            # 집게는 파워 파라미터 유지 (속도/힘 조절 가능)
            if args.grip != "none":
                log_result("running", f"Gripper {args.grip} (power:{args.grip_p})")
                if args.grip == "open":
                    ep_robot.gripper.open(power=args.grip_p)
                elif args.grip == "close":
                    ep_robot.gripper.close(power=args.grip_p)
                time.sleep(1.5)

        # --- FEEDBACK: LED ---
        elif args.action == "FEEDBACK":
            ep_robot.led.set_led(comp="all", r=args.r, g=args.g, b=args.b, effect="on")
            time.sleep(1)

        log_result("success", f"{args.action} task finished")

    except Exception as e:
        log_result("error", str(e))
    finally:
        ep_robot.close()

if __name__ == "__main__":
    low_executor()