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
