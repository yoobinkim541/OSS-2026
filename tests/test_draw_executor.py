"""로봇 실행기 테스트 (실제 시리얼 없이 가짜 컨트롤러 사용).

    python -m unittest discover -s tests -v
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "robot"))
import draw_executor as de  # noqa: E402

CFG = de.load_config()


class FakeSerial:
    """명령마다 정해진 응답을 돌려주는 가짜 Mirobot."""

    IDLE = ("<Idle,Angle(ABCDXYZ):0,0,0,0,0,0,0,"
            "Cartesian coordinate(XYZ RxRyRz):198.668,0.000,230.477,0.000,0.000,0.000,"
            "Pump PWM:0,Valve PWM:0,Motion_MODE:0>")

    def __init__(self, fail_at=None, fail_msg="Soft limit:B"):
        self.lines = []
        self.pending = []
        self.fail_at = fail_at
        self.fail_msg = fail_msg
        self.written = []

    def write(self, data):
        text = data.decode().strip()
        self.written.append(text)
        if text == "?":
            self.pending.append(self.IDLE)
            return
        n = sum(1 for w in self.written if w != "?")
        self.pending.append(self.fail_msg if n == self.fail_at else "ok")

    def readline(self):
        return (self.pending.pop(0) + "\r\n").encode() if self.pending else b""

    def reset_input_buffer(self):
        self.pending.clear()

    def close(self):
        pass


SQUARE = [[(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0), (-10.0, -10.0)]]


class PlannerTest(unittest.TestCase):
    def test_pen_sequence_and_retract_direction(self):
        planner = de.Planner(CFG)
        cmds = planner.plan(SQUARE)
        labels = [label for _, label in cmds]
        self.assertEqual(labels[0], "center pen-up")
        self.assertEqual(labels[1:3], ["stroke 0 travel", "stroke 0 pen-down"])
        self.assertEqual(labels[-2:], ["stroke 0 pen-up", "return center pen-up"])
        up_x = planner.pose(0, 0, False)[0]
        down_x = planner.pose(0, 0, True)[0]
        self.assertAlmostEqual(down_x, CFG["paper_center_tcp_mm"]["x"])
        self.assertAlmostEqual(down_x - up_x, CFG["pen"]["up_clearance_mm"])  # 펜업은 벽에서 멀어짐

    def test_axis_signs(self):
        planner = de.Planner(CFG)
        c = CFG["paper_center_tcp_mm"]
        ry, rz = planner.robot_yz(10, 5)
        self.assertAlmostEqual(ry, c["y"] + CFG["paper_x_to_robot_y_sign"] * 10)
        self.assertAlmostEqual(rz, c["z"] + 5)

    def test_plane_compensation(self):
        cfg = copy.deepcopy(CFG)
        cfg["plane_compensation"]["a_per_mm_y"] = 0.01
        planner = de.Planner(cfg)
        x_left = planner.pose(-50, 0, True)[0]
        x_right = planner.pose(50, 0, True)[0]
        self.assertAlmostEqual(abs(x_left - x_right), 1.0)

    def test_out_of_limits_rejected(self):
        self.assertTrue(de.check_limits([[(0, 0), (80, 0)]], CFG))
        self.assertFalse(de.check_limits(SQUARE, CFG))

    def test_gcode_format(self):
        line = de.Planner(CFG).plan(SQUARE)[0][0]
        self.assertRegex(line, r"^M20 G90 G01 X[-\d.]+ Y[-\d.]+ Z[-\d.]+ A[-\d.]+ B[-\d.]+ C[-\d.]+ F\d+$")


class ExecuteTest(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(CFG)
        self.cfg["ack_timeout_s"] = 0.5
        self.cfg["idle_timeout_s"] = 1.0
        self.cmds = de.Planner(self.cfg).plan(SQUARE)

    def test_status_parsing(self):
        state, tcp, _ = de.MirobotLink(FakeSerial()).query_status()
        self.assertEqual(state, "Idle")
        self.assertEqual(tcp, (198.668, 0.0, 230.477))

    def test_completes_with_acks(self):
        fake = FakeSerial()
        result = de.execute(de.MirobotLink(fake), self.cmds, self.cfg, progress=lambda *_: None)
        self.assertEqual(result["result"], "completed")
        self.assertEqual(result["commands_sent"], len(self.cmds))

    def test_stops_immediately_on_soft_limit(self):
        fake = FakeSerial(fail_at=4)
        result = de.execute(de.MirobotLink(fake), self.cmds, self.cfg, progress=lambda *_: None)
        self.assertEqual(result["result"], "stopped_on_error")
        self.assertIn("Soft limit", result["error"])
        sent = [w for w in fake.written if w != "?"]
        self.assertEqual(len(sent), 4)  # 오류 이후 명령을 더 보내지 않음

    def test_timeout_without_ack(self):
        fake = FakeSerial(fail_at=2, fail_msg="")
        fake.readline = lambda: b""
        result = de.execute(de.MirobotLink(fake), self.cmds, self.cfg, progress=lambda *_: None)
        self.assertEqual(result["result"], "stopped_on_error")


class OrientationTestFileTest(unittest.TestCase):
    def test_orientation_file_is_valid_and_in_limits(self):
        path = Path(__file__).resolve().parent.parent / "trajectories" / "orientation-test-F.json"
        _, strokes = de.load_strokes(path)
        self.assertEqual(len(strokes), 2)
        self.assertFalse(de.check_limits(strokes, CFG))


if __name__ == "__main__":
    unittest.main()
