"""
로봇으로 그리기 작업 — 안전 절차 ①~⑥을 작업 스레드에서 진행 (화면과 무관, GUI 실행 창이 events로 표시)
======================================================================================================
①사전 검사 → ②연결·호밍 → ③시작 위치 → ④최종 확인(사람이 confirm 할 때까지 대기) → ⑤그리는 중 → ⑥끝.
ok 응답마다 진행 파일을 써서 RViz 따라가기가 같은 위치를 보여 줍니다. 자동 복구는 하지 않습니다.

events(kind, **data):
  step      id, status(active|done|failed), message, hint
  progress  acked, total, stroke, strokes, elapsed_s, remaining_s
  rviz      ok, message
  finished  result, record_path
"""

import json
import threading
import time
from datetime import datetime

from . import draw_executor as de
from . import live_progress as lp
from . import paths

CANCELLED = "취소했습니다."


class DrawJob:
    def __init__(self, session, cfg, events, progress_path=None, launch_rviz=None):
        self.session, self.cfg, self.events = session, cfg, events
        self.progress_path = progress_path or (paths.output_dir() / "live_progress.json")
        self.launch_rviz = launch_rviz
        self.state = "idle"
        self.summary = {}
        self.link = None
        self._traj_path = None
        self._snap = None
        self._confirm = threading.Event()
        self._stop = threading.Event()
        self._choice = {}
        self._thread = None

    # ---------------------------------------------------------------- 사람이 누르는 것
    def start(self, virtual=True, virtual_speed=20.0, pending=False):
        """pending: 실물 확인 전 넓은 범위(limits_pending_verification) 허용 — ① 사전 검사부터 적용 (④에서 바꿀 수도 있음)."""
        self._virtual, self._speed, self._pending = bool(virtual), float(virtual_speed), bool(pending)
        self.state = "preflight"      # 첫 이벤트 전에 창을 닫아도 '진행 중'으로 보이게 (스레드 시작 전에)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def confirm(self, air=True, pending=False, checked=False):
        if not checked:
            raise ValueError("종이·펜·주변 확인 체크가 필요합니다")
        if self.state != "confirm":
            raise ValueError("최종 확인 단계가 아닙니다")
        self._choice = {"air": bool(air), "pending": bool(pending)}
        self._confirm.set()

    def stop(self):
        """⑤에서는 다음 명령부터 보내지 않음(멈춤), 그 전 단계에서는 취소."""
        self._stop.set()
        self._confirm.set()

    cancel = stop

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def is_alive(self):
        return bool(self._thread and self._thread.is_alive())

    # ---------------------------------------------------------------- 작업 스레드
    def _step(self, sid, status, message="", hint=""):
        if status == "active":
            self.state = sid
        self.events("step", id=sid, status=status, message=message, hint=hint)

    def _run(self):
        result, record = {"result": "cancelled"}, None
        writer = lp.ProgressWriter(self.progress_path)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        s = self.session
        try:
            # ① 사전 검사
            self._step("preflight", "active", "범위와 로봇 시뮬레이션을 확인합니다")
            if s.sim is None:
                s.simulate()
            # ①에서 그릴 획·시뮬레이션·경로를 한 번에 찍어 둠: 이후 세션이 바뀌어도(편집·이미지 열기)
            # 로봇이 그리는 것, 확인 요약, RViz 궤적, 실행 기록이 모두 같은 그림을 가리키게
            with s.lock:
                if s.result is None or s.sim is None:
                    raise de.DrawError("preflight", "처리 결과나 시뮬레이션이 없습니다.", "이미지를 다시 처리하세요.")
                snap = {"strokes": [[tuple(pt) for pt in st] for st in s.result["strokes_mm"]],
                        "sim_raw": s.sim["raw"], "verdict": s.sim["summary"]["verdict"], "path": s.result["path"],
                        "params": dict(s.result["params"]), "placement": dict(s.result["placement"])}
            self._snap = snap
            verdict = snap["verdict"]
            if verdict.startswith("FAIL"):
                raise de.DrawError("preflight", f"로봇 시뮬레이션이 FAIL입니다: {verdict}",
                                   "그림 크기를 줄이거나 설정을 바꾼 뒤 다시 시뮬레이션하세요.")
            strokes = snap["strokes"]
            pre = de.preflight(strokes, self.cfg, pending=self._pending, air=True)
            pl = snap["placement"]
            self.summary = {"stroke_count": len(strokes), "command_count": len(pre["cmds"]),
                            "estimated_s": pre["timing"]["total_s"],
                            "drawing_mm": [pl["drawing_width_mm"], pl["drawing_height_mm"]],
                            "port": "가상 시뮬레이션" if self._virtual else self.cfg["port"],
                            "virtual": self._virtual, "virtual_speed": self._speed}
            self._step("preflight", "done", f"획 {len(strokes)}개 · 명령 {len(pre['cmds'])}줄 · 시뮬레이션 {verdict.split(':')[0]}")
            # ② 연결·호밍
            self._step("connect", "active", "가상 시뮬레이션에 연결합니다" if self._virtual else
                       "로봇 가운데 버튼을 2초 눌러 호밍하세요. Idle이 되면 자동으로 넘어갑니다")
            self.link = de.open_link(self.cfg, self._virtual, self._speed)
            writer.write(run_id=run_id, state="homing", acked=0, total=len(pre["cmds"]),
                         speed=self._speed if self._virtual else 1.0, trajectory=None, message="호밍 대기")
            tcp = de.connect_and_home(self.link, self.cfg, progress=lambda *_: None, should_cancel=self._stop.is_set)
            self._step("connect", "done", "Idle")
            # ③ 시작 위치
            self._step("start", "active", "펜 끝 위치를 확인합니다")
            off = de.check_start(tcp, self.cfg)
            self._step("start", "done", f"종이 중심에서 {off:.1f} mm")
            # ④ 최종 확인 (사람)
            self._step("confirm", "active", "종이·펜·주변을 확인하고 시작하세요")
            self._confirm.wait()
            if self._stop.is_set():
                raise de.DrawError("confirm", CANCELLED)
            ch = self._choice
            pre = de.preflight(strokes, self.cfg, pending=ch["pending"], air=ch["air"])
            self._step("confirm", "done", "공중 모드" if ch["air"] else "펜으로 그림")
            # ⑤ 그리는 중
            traj = self._write_trajectory(run_id)
            total = len(pre["cmds"])
            writer.write(state="running", acked=0, total=total, trajectory=str(traj), message="그리는 중")
            self._open_rviz(traj)
            self._step("drawing", "active", "그리는 중")
            started, est = time.monotonic(), pre["timing"]["total_s"]
            starts = [i for i, (_, label) in enumerate(pre["cmds"]) if label.endswith("pen-down")]

            def on_ack(acked, n):
                writer.write(state="running", acked=acked)
                el = time.monotonic() - started
                ratio = el / max(est * acked / n, 1e-6) if acked else 1.0   # 실제/예상 속도 비로 보정
                self.events("progress", acked=acked, total=n, stroke=sum(1 for i in starts if i < acked),
                            strokes=len(strokes), elapsed_s=el, remaining_s=est * (1 - acked / n) * ratio)

            result = de.execute(self.link, pre["cmds"], self.cfg, progress=lambda *_: None,
                                on_ack=on_ack, should_stop=self._stop.is_set)
            final = {"completed": "done", "stopped_by_user": "stopped"}.get(result["result"], "error")
            writer.write(state=final, message=result.get("error", result["result"]))
            if final == "done":
                self._step("drawing", "done", "완료")
            else:
                self._step("drawing", "failed", "사용자 멈춤" if final == "stopped" else result.get("error", ""),
                           "자동 복구를 하지 않았습니다. 펜과 로봇 상태를 확인하세요.")
            record = de.write_run_record({
                "strokes_json": snap["path"], "stroke_count": len(strokes), "command_count": total,
                "air_mode": ch["air"], "pending_limits": ch["pending"], "estimated_time": pre["timing"],
                "source": {"image": snap["path"], "params": snap["params"]},
                "virtual": self._virtual, "virtual_speed": self._speed if self._virtual else None,
                "run_id": run_id, "trajectory": str(traj)}, result, self.cfg)
        except de.DrawError as e:
            self._step(e.step, "failed", e.message, e.hint)
            result = {"result": "cancelled" if e.message == CANCELLED else "not_started", "error": e.message}
            writer.write(state="stopped", message=e.message)
        except Exception as e:  # 예상 못 한 오류도 화면에 보이게 (포트는 아래에서 닫음)
            self._step(self.state if self.state not in ("idle", "done") else "preflight", "failed",
                       f"{type(e).__name__}: {e}")
            result = {"result": "error", "error": str(e)}
            writer.write(state="error", message=str(e))
        finally:
            if self.link is not None:
                try:
                    self.link.close()
                except Exception as e:  # 닫기 실패해도 finished는 보내야 GUI 잠금이 풀림
                    self.events("step", id="done", status="failed", message=f"포트 닫기 실패: {e}",
                                hint="USB를 뺐다 꽂고 앱을 다시 시작하세요.")
            self._step("done", "active", "")
            self._step("done", "done", result["result"])
            self.state = "done"
            self.events("finished", result=result, record_path=str(record) if record else None)

    def _write_trajectory(self, run_id):
        from . import mirobot_sim as ms
        path = paths.output_dir() / f"live_traj_{run_id}.json"
        doc = ms.trajectory_doc(self._snap["sim_raw"], self.cfg, self._snap["path"])
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self._traj_path = path
        return path

    def _open_rviz(self, traj):
        """RViz 따라가기를 백그라운드로 엶. WSL이 깨어나는 데 10초 넘게 걸릴 수 있어 드로잉은 기다리지 않음
        (RViz는 진행 파일로 현재 위치를 따라잡음)."""
        launch = self.launch_rviz
        if launch is None:
            from .rviz_launch import launch

        def work():
            try:
                launch(traj, follow=self.progress_path)
                self.events("rviz", ok=True, message="RViz 따라가기를 열었습니다")
            except Exception as e:  # RvizUnavailable 포함: 드로잉은 계속
                self.events("rviz", ok=False, message=str(e))

        threading.Thread(target=work, daemon=True).start()
