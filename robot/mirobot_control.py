"""
Mirobot 실물 제어 스크립트 (Windows 전용)
=========================================
WSL2에서는 usbipd로 넘어온 CH340 시리얼 포트의 read()가 응답을 못 받아오는
문제가 있어, 실물 제어는 Windows에서 직접 pyserial로 처리합니다.

핵심 규칙 (오늘 알아낸 것):
1. Mirobot은 전원 켤 때마다 Alarm 상태로 시작 -> 물리 버튼(중앙 네비게이션 키
   2초 길게)으로 homing 필요. 이 스크립트는 자동 homing은 시도하지 않습니다.
2. 시리얼 연결을 새로 열 때마다 CH340이 보드를 리셋시킴 -> 연결은 한 번만 열고
   계속 재사용해야 함 (이 스크립트는 Mirobot 클래스로 연결을 한 번만 엽니다).
3. homing에는 시간이 걸림 -> Idle 상태가 될 때까지 기다린 뒤에 명령을 보내야 함.

사용 전 준비:
    pip install pyserial

사용법:
    1. Mirobot 전원을 켜고, 물리 버튼(중앙 네비게이션 키)을 2초 이상 눌러
       homing을 먼저 완료하세요 (LED가 파란색 계열로 바뀌고 상태가 Idle이 됨).
    2. 아래 COM_PORT를 실제 포트 번호로 맞추세요 (장치관리자에서 확인 가능).
    3. python robot/mirobot_control.py 로 실행하세요.
"""

import serial
import time

COM_PORT = "COM9"      # 장치관리자에서 확인한 실제 포트로 변경
BAUD_RATE = 115200


class Mirobot:
    """Mirobot과의 시리얼 연결을 한 번만 열고 재사용하는 간단한 래퍼."""

    def __init__(self, port=COM_PORT, baud=BAUD_RATE):
        self.ser = serial.Serial(port, baud, timeout=5)
        time.sleep(2)  # 보드 리셋 후 부팅 대기
        boot_msg = self.ser.read(self.ser.in_waiting or 1)
        print("[부팅 메시지]", boot_msg)

    def get_status(self):
        """현재 상태 문자열을 반환합니다 (예: 'Idle', 'Alarm', 'Home', 'Run')."""
        self.ser.reset_input_buffer()
        self.ser.write(b"?\r\n")
        time.sleep(0.3)
        resp = self.ser.read(self.ser.in_waiting or 1).decode(errors="replace")
        if "<" in resp and "," in resp:
            return resp.split("<")[1].split(",")[0]
        return "unknown"

    def wait_until_idle(self, timeout=60):
        """상태가 Idle이 될 때까지 대기합니다. homing이 끝나길 기다릴 때 사용."""
        print("Idle 상태 대기 중...")
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_status()
            print(f"  현재 상태: {status}")
            if status == "Idle":
                print("Idle 상태 확인됨.")
                return True
            time.sleep(1)
        print("타임아웃: Idle 상태가 되지 않았습니다.")
        return False

    def move_joints(self, j1=0, j2=0, j3=0, j4=0, j5=0, j6=0):
        """관절 각도(도 단위)로 이동합니다. MoveIt에서 계획한 라디안 값은
        (rad / pi) * 180 으로 변환해서 넣으면 됩니다."""
        cmd = f"M21 G90 G00 X{j1} Y{j2} Z{j3} A{j4} B{j5} C{j6}\r\n"
        print(f"[전송] {cmd.strip()}")
        self.ser.write(cmd.encode("utf-8"))
        time.sleep(0.5)
        resp = self.ser.read(self.ser.in_waiting or 1)
        print(f"[응답] {resp}")
        return resp

    def gripper(self, mode):
        """서보 클로 그리퍼를 제어합니다. (M3 S<10~60> 범위)
        mode: 0 = 완전히 열림, 1 = 중간, 2 = 완전히 닫힘
        (실물 테스트로 확인한 값: 10=완전히 열림, 60=완전히 닫힘,
         0/20/30은 데드존이라 반응 없음)
        """
        s_values = {0: 10, 1: 40, 2: 60}
        s_val = s_values.get(mode, 10)
        cmd = f"M3 S{s_val}\r\n"
        print(f"[그리퍼 전송] {cmd.strip()}")
        self.ser.write(cmd.encode("utf-8"))
        time.sleep(1.0)  # 서보가 움직일 시간 확보
        resp = self.ser.read(self.ser.in_waiting or 1)
        print(f"[그리퍼 응답] {resp}")
        return resp

    def gripper_raw(self, s_value):
        """서보 클로용 임의 PWM 값 (대략 10~60 범위에서 유효, 그 밖은 데드존일 수 있음)."""
        cmd = f"M3 S{s_value}\r\n"
        print(f"[그리퍼 전송] {cmd.strip()}")
        self.ser.write(cmd.encode("utf-8"))
        time.sleep(1.0)
        resp = self.ser.read(self.ser.in_waiting or 1)
        print(f"[그리퍼 응답] {resp}")
        return resp

    def pump(self, mode):
        """공압 흡착 펌프를 제어합니다.
        mode: 0 = 끄기, 1 = 흡입(집기, S1000), 2 = 배출(놓기, S500)
        (실물 테스트로 확인한 값: S200~700=배출, S1000=흡입.
         S값이 클수록 흡입이 강해지는 게 아니라, 1000 부근에서
         방향 자체가 바뀌는 구조입니다.)
        """
        s_values = {0: 0, 1: 1000, 2: 500}
        s_val = s_values.get(mode, 0)
        cmd = f"M3 S{s_val}\r\n"
        print(f"[펌프 전송] {cmd.strip()}")
        self.ser.write(cmd.encode("utf-8"))
        time.sleep(1.0)
        resp = self.ser.read(self.ser.in_waiting or 1)
        print(f"[펌프 응답] {resp}")
        return resp

    def pump_raw(self, s_value):
        """펌프용 임의 PWM 값 (공식 값은 0/500/1000, 그 사이도 시도 가능)."""
        cmd = f"M3 S{s_value}\r\n"
        print(f"[펌프 전송] {cmd.strip()}")
        self.ser.write(cmd.encode("utf-8"))
        time.sleep(1.0)
        resp = self.ser.read(self.ser.in_waiting or 1)
        print(f"[펌프 응답] {resp}")
        return resp

    def pick(self, approach, grasp, lift, move_delay=2.5, gripper_delay=1.5):
        """물건을 집는 시퀀스를 순서대로 실행합니다.

        approach: 물건 바로 위 상공 자세, {"j1":.., "j2":.., ...} 형태의 딕셔너리
        grasp:    실제로 물건을 집을 자세 (approach보다 낮은 위치)
        lift:     집은 뒤 들어올릴 자세 (보통 approach와 비슷하거나 더 높음)

        각 자세 딕셔너리는 j1~j6 키만 있으면 되고, 없는 키는 0으로 처리됩니다.
        """
        def _move(pose, label):
            print(f"--- {label} 이동 ---")
            self.move_joints(
                j1=pose.get("j1", 0), j2=pose.get("j2", 0), j3=pose.get("j3", 0),
                j4=pose.get("j4", 0), j5=pose.get("j5", 0), j6=pose.get("j6", 0),
            )
            time.sleep(move_delay)

        # 1. 물건 위 상공으로 접근
        _move(approach, "접근(상공)")

        # 2. 그리퍼 열기
        print("--- 그리퍼 열기 ---")
        self.gripper(0)
        time.sleep(gripper_delay)

        # 3. 물건 높이까지 하강
        _move(grasp, "하강(집기 위치)")

        # 4. 그리퍼 닫기 (집기)
        print("--- 그리퍼 닫기 (집기) ---")
        self.gripper(2)
        time.sleep(gripper_delay)

        # 5. 들어올리기
        _move(lift, "들어올리기")

        print("--- pick 시퀀스 완료 ---")

    def place(self, approach, release, lift, move_delay=2.5, gripper_delay=1.5):
        """집은 물건을 내려놓는 시퀀스 (서보 클로 기준). pick과 대칭되는 구조입니다.

        approach: 내려놓을 위치 바로 위 상공 자세
        release:  실제로 물건을 내려놓을 자세
        lift:     내려놓은 뒤 다시 들어올릴 자세
        """
        def _move(pose, label):
            print(f"--- {label} 이동 ---")
            self.move_joints(
                j1=pose.get("j1", 0), j2=pose.get("j2", 0), j3=pose.get("j3", 0),
                j4=pose.get("j4", 0), j5=pose.get("j5", 0), j6=pose.get("j6", 0),
            )
            time.sleep(move_delay)

        # 1. 목표 위치 상공으로 이동 (물건을 집은 채)
        _move(approach, "접근(상공)")

        # 2. 내려놓을 높이까지 하강
        _move(release, "하강(내려놓기 위치)")

        # 3. 그리퍼 열기 (놓기)
        print("--- 그리퍼 열기 (놓기) ---")
        self.gripper(0)
        time.sleep(gripper_delay)

        # 4. 다시 들어올리기
        _move(lift, "들어올리기")

        print("--- place 시퀀스 완료 ---")

    def pump_pick(self, approach, grasp, lift, move_delay=2.5, pump_delay=1.0):
        """흡착 컵으로 물건을 집는 시퀀스 (pick과 동일 구조, 펌프만 사용)."""
        def _move(pose, label):
            print(f"--- {label} 이동 ---")
            self.move_joints(
                j1=pose.get("j1", 0), j2=pose.get("j2", 0), j3=pose.get("j3", 0),
                j4=pose.get("j4", 0), j5=pose.get("j5", 0), j6=pose.get("j6", 0),
            )
            time.sleep(move_delay)

        _move(approach, "접근(상공)")

        # 하강 전 펌프는 꺼둔 상태 유지
        _move(grasp, "하강(집기 위치)")

        print("--- 펌프 ON (흡입) ---")
        self.pump(1)
        time.sleep(pump_delay)

        _move(lift, "들어올리기")

        print("--- pump_pick 시퀀스 완료 ---")

    def pump_place(self, approach, release, lift, move_delay=2.5, pump_delay=1.0):
        """흡착 컵으로 집은 물건을 내려놓는 시퀀스."""
        def _move(pose, label):
            print(f"--- {label} 이동 ---")
            self.move_joints(
                j1=pose.get("j1", 0), j2=pose.get("j2", 0), j3=pose.get("j3", 0),
                j4=pose.get("j4", 0), j5=pose.get("j5", 0), j6=pose.get("j6", 0),
            )
            time.sleep(move_delay)

        _move(approach, "접근(상공)")
        _move(release, "하강(내려놓기 위치)")

        print("--- 펌프 배출 (놓기) ---")
        self.pump(2)
        time.sleep(pump_delay)

        _move(lift, "들어올리기")

        print("--- pump_place 시퀀스 완료 ---")

    def close(self):
        self.ser.close()


def main():
    mirobot = Mirobot()

    # 이미 물리 버튼으로 homing을 완료했다는 가정하에 상태만 확인합니다.
    # 만약 Alarm 상태로 나오면, 로봇의 중앙 버튼을 2초간 눌러 homing한 뒤
    # 이 스크립트를 다시 실행하세요 (연결을 새로 여는 것 자체가 리셋을
    # 유발하니, 버튼을 누르고 몇 초 뒤에 재실행하는 방식이 안전합니다).
    if not mirobot.wait_until_idle(timeout=60):
        print("Idle이 아닙니다. 로봇 상태를 확인하세요 (Alarm이면 물리 버튼으로 homing).")
        mirobot.close()
        return

    # 예시: joint1을 10도만 살짝 움직여보기 (안전한 테스트용 값)
    mirobot.move_joints(j1=10)
    time.sleep(2)

    # 원위치로 복귀
    mirobot.move_joints(j1=0)

    # 예시: 서보 클로 그리퍼 열기 -> 닫기 테스트 (M3 S10~60 범위)
    mirobot.gripper(0)  # 완전히 열기
    time.sleep(1)
    mirobot.gripper(2)  # 꽉 쥐기
    time.sleep(1)
    mirobot.gripper(0)  # 다시 열기

    # 예시: 공압 펌프(흡착) 테스트 (M3 S0/500/1000 범위)
    # 서보 클로 대신 흡착 컵이 연결되어 있을 때만 사용하세요.
    # mirobot.pump(1)   # 최대 흡입 (S1000)
    # time.sleep(2)
    # mirobot.pump(0)   # 흡입 해제 (S0)

    # ------------------------------------------------------------
    # pick 시퀀스 예시 (아래 관절값은 예시일 뿐, 실제 물건 위치에 맞게
    # 직접 조금씩 바꿔가며 찾아야 합니다 - 사용법은 파일 아래 안내 참고)
    #
    # approach: 물건 바로 위 상공 자세
    # grasp:    실제로 집는 자세 (approach보다 팔을 더 낮춘 값)
    # lift:     집은 뒤 들어올리는 자세
    # ------------------------------------------------------------
    # approach_pose = {"j1": 0, "j2": -20, "j3": 20, "j4": 0, "j5": 30, "j6": 0}
    # grasp_pose    = {"j1": 0, "j2": -10, "j3": 30, "j4": 0, "j5": 45, "j6": 0}
    # lift_pose     = {"j1": 0, "j2": -20, "j3": 20, "j4": 0, "j5": 30, "j6": 0}
    #
    # 서보 클로로 집을 때:
    # mirobot.pick(approach_pose, grasp_pose, lift_pose)
    #
    # 흡착 컵으로 집을 때 (아래 pump_pick 참고):
    # mirobot.pump_pick(approach_pose, grasp_pose, lift_pose)

    mirobot.close()


if __name__ == "__main__":
    main()
