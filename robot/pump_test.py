"""
펌프(흡입) 테스트 스크립트 - 공식 SDK 값 기준
===========================================
gripper()와 pump()는 둘 다 "M3 S<값>"을 보내는 같은 명령입니다.
다른 건 값의 범위예요:
  - 서보 클로(gripper): S10~S60 정도의 작은 값 (각도 스케일)
  - 공압 펌프(pump):     S500~S1000 정도의 큰 값 (파워/duty 스케일)

즉 GPIO 채널이 다른 게 아니라, 같은 포트에 뭘 꽂았느냐에 따라
그 값이 다르게 해석되는 구조입니다. 지금까지 S60까지만 시도해서
반응이 없었던 거고, 이 스크립트는 S1000까지 확인합니다.

사용법: python robot/pump_test.py
"""

import serial
import time

COM_PORT = "COM9"
BAUD_RATE = 115200


def main():
    s = serial.Serial(COM_PORT, BAUD_RATE, timeout=5)
    time.sleep(2)
    print("[부팅 메시지]", s.read(s.in_waiting or 1))

    s.write(b"?\r\n")
    time.sleep(0.5)
    print("[상태]", s.read(s.in_waiting or 1))

    input("\nIdle 상태인 것을 확인했으면 Enter를 눌러 펌프 테스트를 시작하세요...")

    # 공식 SDK 값(500, 1000)을 포함해서 넓게 스캔
    test_values = [0, 100, 300, 500, 700, 1000]
    for val in test_values:
        input(f"\nS{val} 전송하려면 Enter (흡착 컵/공압 박스 보고 계세요)...")
        cmd = f"M3 S{val}\r\n"
        print(f"[전송] {cmd.strip()}")
        s.write(cmd.encode("utf-8"))
        time.sleep(1.5)
        print(f"[응답] {s.read(s.in_waiting or 1)}")
        reacted = input("  소리/진동/흡입 있었나요? (y/n): ")
        print(f"  -> S{val}: {'반응!' if reacted.lower() == 'y' else '무반응'}")

    # 마지막엔 반드시 꺼서 마무리
    s.write(b"M3 S0\r\n")
    time.sleep(1)
    print("[종료] 펌프 OFF:", s.read(s.in_waiting or 1))

    s.close()
    print("\n테스트 완료. 반응이 있었던 S값이 실제 펌프 작동 범위입니다.")


if __name__ == "__main__":
    main()
