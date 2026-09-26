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
                app.proposal_bar.apply_btn.invoke()                        # 적용은 작업 스레드에서
                self.assertTrue(pump(root, app, lambda: app._workers == 0 and s.table[sid]["kind"] == "candidate"))
                self.assertFalse(app.proposal_bar.winfo_manager())         # 적용하면 사라짐
        finally:
            app._on_close()

    def test_thousands_of_proposals_draw_fast_with_capped_labels(self):
        import numpy as np
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                s = app.session
                s.table = {i + 1: {"kind": "stroke", "reason": "",
                                   "poly": np.array([[10 + (i % 60) * 12, 10 + (i // 60) * 12],
                                                     [16 + (i % 60) * 12, 14 + (i // 60) * 12]], float)}
                           for i in range(3000)}
                s.next_id = 3001
                s.propose_edits([{"op": "delete", "ids": list(range(1, 200))}] +
                                [{"op": "delete", "ids": list(range(k, k + 200))} for k in range(200, 3000, 200)])
                app.refresh_proposals()
                t0 = time.time()
                app.select_stage("edit")
                app.view.canvas.draw()
                self.assertLess(time.time() - t0, 5.0)
                self.assertLessEqual(len(app.view.ax.texts), 450)
                self.assertLessEqual(len(app.view.ax.lines), 4)       # 제안마다 plot 하지 않음
        finally:
            app._on_close()


    def test_gui_minor_behaviours(self):
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                s = app.session
                # 1) 뺀 표시는 번호를 새로 매기면 풀림
                sid = next(i for i, e in s.table.items() if e["kind"] == "stroke")
                s.propose_edits([{"op": "delete", "ids": [sid]}])
                app.refresh_proposals()
                app.proposal_bar._toggle(sid)
                app._on_param("canny_low", s.params["canny_low"] + 4)
                self.assertTrue(pump(root, app, lambda: app._workers == 0 and s.proposals == {}))
                sid = next(i for i, e in s.table.items() if e["kind"] == "stroke")
                s.propose_edits([{"op": "delete", "ids": [sid]}])
                app.refresh_proposals()
                self.assertEqual(app.proposal_bar.excluded, set())
                # 2) 적용은 작업 스레드에서 (화면이 멈추지 않게) 끝나면 반영
                app.proposal_bar.apply_btn.invoke()
                self.assertTrue(pump(root, app, lambda: s.table[sid]["kind"] == "candidate" and app._workers == 0))
                # 3) 에이전트 작업 중 프리셋을 바꾸면, 끝난 뒤 다시 계산
                app.agent_busy(True)
                app.detail_seg.set("낮음")
                app.apply_detail_preset()
                root.update()
                app.agent_busy(False)
                self.assertTrue(pump(root, app, lambda: app._workers == 0 and app.result["detail"] == "low"))
        finally:
            app._on_close()


    def test_stage_strip_shows_numbers_results_and_compare(self):
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                sm = app.session.stage_summaries()
                txt = app.strip.buttons["trace"].cget("text")
                self.assertTrue(txt.startswith("④ 뼈대·획"))
                self.assertIn(sm["trace"], txt)
                app.select_stage("dedupe")
                root.update()
                self.assertIn("→", app.view.subtitle.cget("text"))      # 설명 + 이전 대비 변화
                shown = app.view.image
                app.view.hold_compare(True)                             # 누르고 있는 동안 이전 단계
                self.assertIsNot(app.view.image, shown)
                self.assertTrue(app.view.title.cget("text").startswith("④"))   # ⑤의 이전 = ④
                app.view.hold_compare(False)
                self.assertIs(app.view.image, shown)
        finally:
            app._on_close()


if __name__ == "__main__":
    unittest.main()
