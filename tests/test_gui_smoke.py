"""GUI 스모크: 창을 띄워 이미지 열기 → 값 변경 → 자동 재계산이 끝나는지 (화면이 없으면 건너뜀)."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

import golden  # noqa: E402


def make_app():
    try:
        import customtkinter as ctk
        root = ctk.CTk()
    except Exception as e:   # 화면(DISPLAY) 없음, Tk 없음
        raise unittest.SkipTest(f"GUI 없음: {e}")
    from mirobot_sketch import gui
    root.withdraw()
    return root, gui.SketchApp(root)


def pump(root, app, until, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


class GuiSmokeTest(unittest.TestCase):
    def test_open_change_param_recomputes(self):
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                n = app.result["timing"]["stroke_count"]
                for sid in ("source", "edges", "trace", "simplify", "edit", "paper"):
                    app.select_stage(sid)
                    root.update()
                app._on_param("epsilon_px", 4.0)
                self.assertTrue(pump(root, app, lambda: app._workers == 0 and
                                     app.result["params"]["epsilon_px"] == 4.0))
                self.assertEqual(app.result["timing"]["stroke_count"], n)   # 단순화는 획 수를 안 바꿈
        finally:
            app._on_close()

    def test_edit_stage_shows_proposals_and_applies(self):
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                s = app.session
                sid = next(i for i, e in s.table.items() if e["kind"] == "stroke")
                s.propose_edits([{"op": "delete", "ids": [sid]}])
                app.refresh_proposals()
                app.select_stage("edit")
                root.update()
                self.assertTrue(app.proposal_bar.winfo_manager())          # 제안이 있으면 바가 배치됨
                self.assertIn(sid, app.proposal_bar.chips)
                app.proposal_bar.apply_btn.invoke()
                root.update()
                self.assertEqual(s.table[sid]["kind"], "candidate")
                self.assertFalse(app.proposal_bar.winfo_manager())         # 적용하면 사라짐
        finally:
            app._on_close()


if __name__ == "__main__":
    unittest.main()
