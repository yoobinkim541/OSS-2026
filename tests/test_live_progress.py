"""진행 파일(원자적 쓰기)과 RViz 따라가기 위치 계산."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import live_progress as lp  # noqa: E402


def points(cmds):
    """cmd 번호 목록 -> 궤적 점 (1mm 간격 가정)."""
    return [{"cmd": c} for c in cmds]


# 시작 자세 1점, 명령0: 3점, 명령1: 10점, 명령2: 2점
PTS = points([-1] + [0] * 3 + [1] * 10 + [2] * 2)
FEED = [600.0, 60.0, 600.0]          # mm/min -> 명령1은 1 mm/s


class FollowTrackTest(unittest.TestCase):
    def setUp(self):
        self.tr = lp.FollowTrack(PTS, FEED)

    def test_command_end_indices(self):
        self.assertEqual(self.tr.cmd_end, [3, 13, 15])

    def test_acked_commands_are_final(self):
        self.assertEqual(self.tr.index({"state": "running", "acked": 0, "t": 100.0}, 100.0), 0)
        self.assertEqual(self.tr.index({"state": "running", "acked": 1, "t": 100.0}, 100.0), 3)

    def test_interpolates_but_never_passes_next_command_end(self):
        p = {"state": "running", "acked": 1, "t": 100.0, "speed": 1.0}
        self.assertEqual(self.tr.index(p, 103.0), 6)              # 1 mm/s * 3 s = 3점 앞으로
        self.assertEqual(self.tr.index(p, 1000.0), 13)            # 응답이 늦어도 명령1의 끝에서 기다림
        self.assertEqual(self.tr.index({**p, "speed": 2.0}, 103.0), 9)   # 배속 반영

    def test_stopped_error_done_hold_position(self):
        for st in ("stopped", "error", "done"):
            self.assertEqual(self.tr.index({"state": st, "acked": 1, "t": 100.0}, 200.0), 3, st)
        self.assertEqual(self.tr.index({"state": "done", "acked": 3, "t": 1.0}, 2.0), 15)

    def test_missing_progress_stays_at_start(self):
        self.assertEqual(self.tr.index(None, 5.0), 0)


class ProgressFileTest(unittest.TestCase):
    def test_write_and_read_roundtrip_keeps_previous_fields(self):
        with tempfile.TemporaryDirectory() as d:
            w = lp.ProgressWriter(Path(d) / "p.json")
            w.write(run_id="r1", total=10, state="running", acked=0)
            w.write(acked=4)
            got = lp.read_progress(Path(d) / "p.json")
            self.assertEqual((got["run_id"], got["total"], got["acked"]), ("r1", 10, 4))
            self.assertIn("t", got)

    def test_reader_never_sees_half_written_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            w = lp.ProgressWriter(path)
            w.write(run_id="r", total=5000, state="running", acked=0, note="x" * 5000)
            stop, bad = threading.Event(), []

            def reader():
                while not stop.is_set():
                    try:
                        json.loads(path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError as e:
                        bad.append(e)
                    except (PermissionError, FileNotFoundError):
                        pass

            t = threading.Thread(target=reader)
            t.start()
            for i in range(300):
                w.write(acked=i)
            stop.set()
            t.join()
            self.assertEqual(bad, [])

    def test_replace_is_retried_when_file_is_briefly_locked(self):
        with tempfile.TemporaryDirectory() as d:
            w = lp.ProgressWriter(Path(d) / "p.json")
            real = lp.os.replace
            calls = []

            def flaky(a, b):
                calls.append(1)
                if len(calls) < 3:
                    raise PermissionError("locked")
                return real(a, b)

            with mock.patch.object(lp.os, "replace", side_effect=flaky):
                w.write(state="running")
            self.assertEqual(len(calls), 3)
            self.assertEqual(lp.read_progress(Path(d) / "p.json")["state"], "running")

    def test_write_never_raises_and_retries_tmp_open(self):
        with tempfile.TemporaryDirectory() as d:
            w = lp.ProgressWriter(Path(d) / "p.json")
            real_open = open
            calls = []

            def flaky_open(path, *a, **k):
                if str(path).endswith(".tmp"):
                    calls.append(1)
                    if len(calls) < 3:
                        raise PermissionError("tmp locked")
                return real_open(path, *a, **k)

            with mock.patch("builtins.open", side_effect=flaky_open):
                w.write(state="running")
            self.assertEqual(lp.read_progress(Path(d) / "p.json")["state"], "running")
            with mock.patch.object(lp.os, "replace", side_effect=OSError("always locked")):
                w.write(state="done")                          # 예외 없이 넘어가고 기록만 남김
            self.assertIn("always locked", w.last_error)

    def test_read_missing_or_broken(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(lp.read_progress(Path(d) / "none.json"))
            (Path(d) / "b.json").write_text("{", encoding="utf-8")
            self.assertIsNone(lp.read_progress(Path(d) / "b.json"))

    def test_to_local_path(self):
        with mock.patch.object(lp.sys, "platform", "linux"):
            self.assertEqual(lp.to_local_path("C:\\Users\\a b\\x.json"), "/mnt/c/Users/a b/x.json")
            self.assertEqual(lp.to_local_path("/home/u/x.json"), "/home/u/x.json")
        with mock.patch.object(lp.sys, "platform", "win32"):
            self.assertEqual(lp.to_local_path("C:\\x.json"), "C:\\x.json")


if __name__ == "__main__":
    unittest.main()
