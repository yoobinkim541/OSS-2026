"""GUI 스모크: 창을 띄워 이미지 열기 → 값 변경 → 자동 재계산이 끝나는지 (화면이 없으면 건너뜀)."""

import sys
import tempfile
import time
import unittest
from unittest import mock
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


def close_quietly(app):
    """이미 닫혔으면 아무것도 안 함."""
    try:
        if app.root.winfo_exists():
            app._on_close()
    except Exception:  # TclError: 이미 파괴됨
        pass


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


    def _patched_dirs(self, d):
        return (mock.patch("mirobot_sketch.draw_executor.paths.runs_dir", lambda: Path(d) / "runs"),
                mock.patch("mirobot_sketch.draw_executor.paths.output_dir", lambda: Path(d)))

    def test_draw_window_virtual_run(self):
        root, app = make_app()
        try:
            with tempfile.TemporaryDirectory() as d:
                p1, p2 = self._patched_dirs(d)
                with p1, p2:
                    p = Path(d) / "line.png"
                    cv2.imwrite(str(p), golden.synthetic_images()["line"])
                    app.load_image(p)
                    self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                    app.session.update_params({"box_mm": 60, "epsilon_px": 4.0})
                    app._schedule_recompute(0)
                    self.assertTrue(pump(root, app, lambda: app._workers == 0 and
                                         app.result["params"]["box_mm"] == 60))
                    w = app.open_draw_window(launch_rviz=lambda *a, **k: None)
                    w.virtual_var.set(True)
                    w.speed_var.set("500×")
                    w.begin()
                    self.assertTrue(pump(root, app, lambda: w.job.state == "confirm", timeout=60))
                    self.assertEqual(str(w.start_btn.cget("state")), "disabled")      # 체크 전에는 꺼짐
                    w.check_var.set(True)
                    w._on_check()
                    self.assertEqual(str(w.start_btn.cget("state")), "normal")
                    w.on_start()
                    self.assertTrue(app.drawing)                                        # 실행 중 잠금
                    self.assertTrue(app.session.drawing_lock)
                    self.assertTrue(pump(root, app, lambda: w.finished is not None, timeout=120))
                    self.assertEqual(w.finished["result"]["result"], "completed")
                    self.assertFalse(app.drawing)
                    self.assertTrue(list((Path(d) / "runs").glob("run-*.json")))
                    w.close()
        finally:
            app._on_close()

    def test_closing_app_while_drawing_stops_the_job(self):
        root, app = make_app()
        self.addCleanup(close_quietly, app)   # 실패해도 창을 닫아 다음 테스트에 안 번지게
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = self._patched_dirs(d)
            with p1, p2, mock.patch("mirobot_sketch.draw_window.messagebox.askyesno", return_value=True):
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                w = app.open_draw_window(launch_rviz=lambda *a, **k: None)
                w.virtual_var.set(True)
                w.speed_var.set("1×")
                w.begin()
                self.assertTrue(pump(root, app, lambda: w.job.state == "confirm", timeout=60))
                w.check_var.set(True)
                w._on_check()
                w.on_start()
                self.assertTrue(pump(root, app, lambda: w.job.state == "drawing", timeout=10))
                job = w.job
                app._on_close()                                   # 앱 종료: 묻고(예) 멈춘 뒤 닫음
                job.join(5)
                self.assertEqual(job.state, "done")
                self.assertEqual(job.link.state, "closed")        # 포트(가상) 닫힘


    def test_lock_starts_at_begin_and_stuck_close_keeps_lock(self):
        root, app = make_app()
        self.addCleanup(close_quietly, app)
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = self._patched_dirs(d)
            with p1, p2, mock.patch("mirobot_sketch.draw_window.messagebox.askyesno", return_value=True), \
                    mock.patch("mirobot_sketch.draw_window.messagebox.showwarning"):
                p = Path(d) / "line.png"
                cv2.imwrite(str(p), golden.synthetic_images()["line"])
                app.load_image(p)
                self.assertTrue(pump(root, app, lambda: app.result is not None and app._workers == 0))
                w = app.open_draw_window(launch_rviz=lambda *a, **k: None)
                w.begin()
                self.assertTrue(app.drawing)                          # ①부터 잠금 (호밍 중 편집 금지)
                self.assertEqual(str(app.open_btn.cget("state")), "disabled")
                self.assertEqual(str(app.traj_btn.cget("state")), "disabled")
                self.assertTrue(pump(root, app, lambda: w.job.state == "confirm", timeout=60))
                real_job = w.job

                class Stuck:                                          # 로봇 응답을 기다리느라 안 끝나는 작업
                    state = "drawing"

                    def stop(self):
                        pass

                    def join(self, timeout=None):
                        pass

                    def is_alive(self):
                        return True

                w.job, w.close_timeout = Stuck(), 0.1
                self.assertFalse(w.close())                           # 안 닫고 잠금 유지
                self.assertTrue(w.winfo_exists())
                self.assertTrue(app.drawing)
                w.job = real_job
                self.assertTrue(w.close())
                self.assertFalse(app.drawing)


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
