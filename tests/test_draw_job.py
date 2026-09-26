"""실행 작업(가상 시뮬레이션): 단계 순서, 확인 전 대기, 멈춤, 기록, 진행 파일."""

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import draw_executor as de  # noqa: E402
from mirobot_sketch import live_progress as lp  # noqa: E402
from mirobot_sketch.draw_job import DrawJob  # noqa: E402
from mirobot_sketch.session import SketchSession  # noqa: E402

import golden  # noqa: E402


class Recorder:
    def __init__(self):
        self.events, self.lock = [], threading.Lock()
        self.ready = threading.Event()
        self.done = threading.Event()

    def __call__(self, kind, **data):
        with self.lock:
            self.events.append((kind, data))
        if kind == "step" and data["id"] == "confirm" and data["status"] == "active":
            self.ready.set()
        if kind == "finished":
            self.done.set()

    def steps(self):
        return [(d["id"], d["status"]) for k, d in self.events if k == "step"]


class DrawJobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        p = Path(cls.tmp.name) / "line.png"
        cv2.imwrite(str(p), golden.synthetic_images()["line"])
        cls.session = SketchSession()
        cls.session.set_image(p)
        cls.session.update_params({"box_mm": 60, "epsilon_px": 4.0})
        cls.session.run_current()
        cls.session.simulate()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def job(self, rec, launch_rviz=lambda *a, **k: None):
        d = Path(self.tmp.name)
        for name, fn in (("runs_dir", lambda: d / "runs"), ("output_dir", lambda: d)):
            patcher = mock.patch.object(de.paths, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        return DrawJob(self.session, self.session.cfg, rec, progress_path=d / "live.json", launch_rviz=launch_rviz)

    def test_waits_for_confirmation_then_runs_all_steps(self):
        rec = Recorder()
        job = self.job(rec)
        job.start(virtual=True, virtual_speed=500)
        self.assertTrue(rec.ready.wait(10))
        self.assertEqual(job.state, "confirm")
        self.assertIn("command_count", job.summary)
        with self.assertRaises(ValueError):
            job.confirm(checked=False)                         # 확인 체크 없이는 시작 안 함
        job.confirm(air=True, checked=True)
        self.assertTrue(rec.done.wait(60))
        done_ids = [i for i, st in rec.steps() if st == "done"]
        self.assertEqual(done_ids, ["preflight", "connect", "start", "confirm", "drawing", "done"])
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "completed")
        self.assertTrue(Path(fin["record_path"]).exists())
        prog = [d for k, d in rec.events if k == "progress"]
        self.assertEqual(prog[-1]["acked"], prog[-1]["total"])
        live = lp.read_progress(Path(self.tmp.name) / "live.json")
        self.assertEqual((live["state"], live["acked"]), ("done", live["total"]))
        self.assertTrue(Path(lp.to_local_path(live["trajectory"])).exists())

    def test_stop_during_drawing(self):
        rec = Recorder()
        job = self.job(rec)
        job.start(virtual=True, virtual_speed=1)
        self.assertTrue(rec.ready.wait(10))
        job.confirm(checked=True)
        threading.Timer(0.5, job.stop).start()
        self.assertTrue(rec.done.wait(5))
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "stopped_by_user")
        self.assertEqual(lp.read_progress(Path(self.tmp.name) / "live.json")["state"], "stopped")
        self.assertEqual(job.link.state, "closed")

    def test_cancel_at_confirmation_closes_without_record(self):
        rec = Recorder()
        job = self.job(rec)
        job.start(virtual=True, virtual_speed=500)
        self.assertTrue(rec.ready.wait(10))
        job.cancel()
        self.assertTrue(rec.done.wait(5))
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "cancelled")
        self.assertIsNone(fin["record_path"])
        self.assertEqual(job.link.state, "closed")

    def test_wide_range_choice_applies_to_preflight(self):
        big = SketchSession()
        big.set_image(Path(self.tmp.name) / "line.png")
        big.update_params({"box_mm": 110, "epsilon_px": 4.0})       # ±55mm: 실행기 허용(±50) 밖, 넓은 범위(±60) 안
        big.run_current()
        big.simulate()
        for pending, expect in ((False, "failed"), (True, "confirm")):
            rec = Recorder()
            job = self.job(rec)
            job.session = big
            job.start(virtual=True, virtual_speed=500, pending=pending)
            if expect == "confirm":
                self.assertTrue(rec.ready.wait(20))
                job.cancel()
            self.assertTrue(rec.done.wait(20))
            pre = [st for i, st in rec.steps() if i == "preflight"]
            self.assertEqual(pre[-1], "failed" if expect == "failed" else "done", pending)

    def test_slow_rviz_launch_does_not_delay_drawing(self):
        import time
        rec = Recorder()
        job = self.job(rec, launch_rviz=lambda *a, **k: time.sleep(3))   # WSL이 깨어나는 데 오래 걸리는 경우
        job.start(virtual=True, virtual_speed=500)
        self.assertTrue(rec.ready.wait(10))
        t0 = time.monotonic()
        job.confirm(checked=True)
        first = threading.Event()
        orig = job.events

        def watch(kind, **d):
            if kind == "progress":
                first.set()
            orig(kind, **d)

        job.events = watch
        self.assertTrue(first.wait(5))
        self.assertLess(time.monotonic() - t0, 1.0)       # RViz를 기다리지 않고 바로 첫 명령
        self.assertTrue(rec.done.wait(60))

    def test_state_is_active_as_soon_as_started(self):
        rec = Recorder()
        job = self.job(rec)
        job.start(virtual=True, virtual_speed=500)
        self.assertNotEqual(job.state, "idle")             # 첫 이벤트 전에 닫아도 '진행 중'으로 보이게
        self.assertTrue(rec.ready.wait(10))
        job.cancel()
        self.assertTrue(rec.done.wait(5))

    def test_session_changes_after_step1_do_not_affect_the_run(self):
        rec = Recorder()
        job = self.job(rec)
        path = self.session.result["path"]
        job.start(virtual=True, virtual_speed=500)
        self.assertTrue(rec.ready.wait(10))
        saved = (self.session.result, self.session.sim)
        self.session.result, self.session.sim = None, None     # 호밍 중에 이미지를 바꾸거나 편집한 상황
        try:
            job.confirm(checked=True)
            self.assertTrue(rec.done.wait(60))
        finally:
            self.session.result, self.session.sim = saved
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "completed")   # ①에서 찍어 둔 획으로 끝까지
        self.assertTrue(Path(fin["record_path"]).exists())
        import json
        self.assertEqual(json.loads(Path(fin["record_path"]).read_text(encoding="utf-8"))["strokes_json"], path)

    def test_progress_file_failures_never_abort_drawing(self):
        rec = Recorder()
        job = self.job(rec)
        with mock.patch.object(lp.os, "replace", side_effect=OSError("locked by antivirus")):
            job.start(virtual=True, virtual_speed=500)
            self.assertTrue(rec.ready.wait(10))
            job.confirm(checked=True)
            self.assertTrue(rec.done.wait(60))
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "completed")

    def test_port_close_error_still_finishes(self):
        rec = Recorder()
        job = self.job(rec)
        from mirobot_sketch import virtual_robot
        with mock.patch.object(virtual_robot.VirtualMirobotLink, "close", side_effect=OSError("close failed")):
            job.start(virtual=True, virtual_speed=500)
            self.assertTrue(rec.ready.wait(10))
            job.cancel()
            self.assertTrue(rec.done.wait(5))                 # finished가 와야 GUI 잠금이 풀림

    def test_rviz_unavailable_does_not_block_drawing(self):
        rec = Recorder()

        def no_rviz(*a, **k):
            from mirobot_sketch.rviz_launch import RvizUnavailable
            raise RvizUnavailable("ROS 없음")

        job = self.job(rec, launch_rviz=no_rviz)
        job.start(virtual=True, virtual_speed=500)
        self.assertTrue(rec.ready.wait(10))
        job.confirm(checked=True)
        self.assertTrue(rec.done.wait(60))
        self.assertTrue(any(k == "rviz" and not d["ok"] for k, d in rec.events))
        fin = next(d for k, d in rec.events if k == "finished")
        self.assertEqual(fin["result"]["result"], "completed")


if __name__ == "__main__":
    unittest.main()
