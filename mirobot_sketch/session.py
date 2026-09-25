"""
SketchSession — 이미지 한 장의 작업 상태 (GUI와 에이전트가 함께 사용)
======================================================================
이미지, 처리 설정, 처리 결과(획), 편집 기록(되돌리기), 시뮬레이션 결과를 한곳에
둡니다. GUI 버튼과 에이전트 도구가 모두 이 객체를 통해 같은 상태를 바꾸므로,
화면과 대화가 어긋나지 않습니다. Tk에 의존하지 않아 단위 테스트가 가능합니다.

스레드: 무거운 계산은 호출한 스레드에서 돌고, 상태 변경은 lock으로 보호합니다.
"""

import dataclasses
import threading

import cv2
import numpy as np

from . import draw_executor as de
from . import paper_mapping as pm
from . import paths, presets, stages
from . import sketch_pipeline as sp


class SessionError(Exception):
    """사용자·에이전트에게 그대로 보여 줄 수 있는 오류."""


class SketchSession:
    def __init__(self, cfg=None):
        self.cfg = cfg or de.load_config()
        self.lock = threading.RLock()
        self._run_lock = threading.Lock()   # 파이프라인 계산은 한 번에 하나 (GUI 자동 재계산 + 에이전트)
        self.image_path = None
        self.color = None
        self.image_type = "illustration"
        self.detail = "high"
        self.generation = 0                 # 설정이 바뀔 때마다 +1 (오래된 계산 결과를 버리는 기준)
        self.params = stages.default_params()
        self.apply_preset("illustration")
        self.pipeline = stages.Pipeline()
        self._inputs_cache = {}
        self.result = None
        self.history = []      # 되돌리기용 (strokes_px, strokes_mm, 설명)
        self.edit_log = []     # 적용된 편집 설명 (재현·기록용)
        self.sim = None

    # ------------------------------------------------------------ 설정
    def param_specs(self):
        """단계 정의의 조절 항목. box_mm 상한은 설정 파일의 실물 미확인 범위(±60mm -> 120)."""
        plim = self.cfg["limits_pending_verification"]["max_abs_paper_x_mm"] * 2
        specs = dict(stages.PARAM_SPECS)
        specs["box_mm"] = dataclasses.replace(specs["box_mm"], hi=plim)
        return specs

    def apply_preset(self, image_type=None, detail=None):
        """이미지 종류 프리셋(상세도·rembg·미디언)과 상세도 프리셋(Canny·길이·단순화)을 적용."""
        with self.lock:
            if image_type:
                if image_type not in presets.IMAGE_TYPES:
                    raise SessionError(f"알 수 없는 이미지 종류: {image_type} (가능: {', '.join(presets.IMAGE_TYPES)})")
                t = presets.IMAGE_TYPES[image_type]
                self.image_type = image_type
                self.detail = t["detail"]
                self.params.update(rembg=t["rembg"], median_ksize=t["median"])
            if detail:
                if detail not in presets.DETAIL_PRESETS:
                    raise SessionError(f"알 수 없는 상세도: {detail} (가능: low, medium, high)")
                self.detail = detail
            lo, hi, ml, eps = presets.DETAIL_PRESETS[self.detail]
            self.params.update(canny_low=lo, canny_high=hi, min_length_px=ml, epsilon_px=eps)
            self.generation += 1

    def update_params(self, changes):
        """개별 설정 변경. 범위를 벗어나면 잘라서 적용하고 실제 적용값을 돌려줌."""
        specs = self.param_specs()
        applied = {}
        with self.lock:
            for k, v in changes.items():
                if k == "line_source":          # 예전 이름: canny -> 밝기(luma), dark -> 어두운 선
                    if v not in ("canny", "dark"):
                        raise SessionError("line_source는 canny 또는 dark")
                    k, v = "edge_mode", ("dark" if v == "dark" else "luma")
                spec = specs.get(k)
                if spec is None:
                    raise SessionError(f"알 수 없는 설정: {k}")
                try:
                    v = spec.clamp(v)
                except (TypeError, ValueError) as e:
                    raise SessionError(str(e)) from None
                self.params[k] = v
                applied[k] = v
            if applied:
                self.generation += 1
        return applied

    # ------------------------------------------------------------ 처리
    def set_image(self, path):
        gray = sp.load_gray(path)
        color = sp.load_color(path)
        with self.lock:
            self.image_path = str(path)
            self.color = color            # 화면·에이전트에 보여 줄 컬러 원본
            self._inputs_cache = {False: {"gray": gray, "color": color}}
            self.result = self.sim = None
            self.history, self.edit_log = [], []
            self.generation += 1

    def _inputs(self, rembg):
        if rembg not in self._inputs_cache:
            color = sp.remove_background_bgr(self.image_path, cache_dir=paths.cache_dir())
            self._inputs_cache[rembg] = {"gray": cv2.cvtColor(color, cv2.COLOR_BGR2GRAY), "color": color}
        return self._inputs_cache[rembg], (self.image_path, bool(rembg))

    def dirty_stages(self):
        """지금 설정으로 다시 계산될 단계들 (GUI가 흐리게 표시)."""
        with self.lock:
            p = dict(self.params)
        first = self.pipeline.dirty_from((self.image_path, bool(p["rembg"])), p)
        ids = [s.id for s in stages.ALL_STAGES]
        start = ids.index(first) if first else ids.index("edit")
        return ids[start:]

    def run(self):
        """현재 설정으로 처리. 더 새로운 설정이 들어와 계산을 버렸으면 None."""
        if not self.image_path:
            raise SessionError("먼저 이미지를 열어야 합니다.")
        with self._run_lock:
            with self.lock:
                p, gen = dict(self.params), self.generation
            inputs, ikey = self._inputs(bool(p["rembg"]))
            try:
                outs = self.pipeline.run(inputs, ikey, p, is_current=lambda: self.generation == gen)
            except stages.StaleRun:
                return None
            strokes_px = sp.order_strokes(outs["simplify"]["strokes"])
            if not strokes_px:
                raise SessionError("획이 없습니다. 상세도를 높이거나 Canny 하한을 낮춰 보세요.")
            strokes_mm, placement = pm.pixels_to_paper(strokes_px, box_mm=(p["box_mm"], p["box_mm"]))
            with self.lock:
                if self.generation != gen:
                    return None
                self.result = {"base": inputs["gray"], "color": self.color, "edges": outs["edges"]["edges"],
                               "stages": outs, "placement": placement, "path": self.image_path,
                               "params": p, "image_type": self.image_type, "detail": self.detail}
                self.history, self.edit_log, self.sim = [], [], None
                self._set_strokes(list(strokes_px), list(strokes_mm))
                return self.result

    def run_current(self, max_tries=5):
        """최신 설정의 결과가 나올 때까지 다시 시도 (에이전트용)."""
        for _ in range(max_tries):
            r = self.run()
            if r is not None:
                return r
        raise SessionError("설정이 계속 바뀌고 있어 계산을 마치지 못했습니다. 잠시 후 다시 시도하세요.")

    def _set_strokes(self, strokes_px, strokes_mm):
        """획이 바뀔 때마다 시간·미리보기·범위 검사를 다시 계산."""
        r = self.result
        r["strokes_px"], r["strokes_mm"] = strokes_px, strokes_mm
        lists = [[tuple(pt) for pt in s] for s in strokes_mm]
        r["timing"] = de.estimate_time(lists, self.cfg)
        lim = self.cfg["limits"]["max_abs_paper_x_mm"]
        plim = self.cfg["limits_pending_verification"]["max_abs_paper_x_mm"]
        r["paper"] = pm.render_paper_preview(strokes_mm, self.cfg["pen"].get("line_width_mm", 0.5), 4.0,
                                             limit_mm=lim, pending_limit_mm=plim)
        r["out_of_limits"] = len(de.check_limits(lists, self.cfg))
        r["out_of_pending"] = len(de.check_limits(lists, self.cfg, pending=True))
        self.sim = None

    def _need_result(self):
        if not self.result:
            raise SessionError("먼저 처리를 실행해야 합니다.")

    # ------------------------------------------------------------ 편집
    def _push(self, desc):
        r = self.result
        self.history.append((list(r["strokes_px"]), list(r["strokes_mm"]), desc))

    def delete_strokes(self, ids):
        with self.lock:
            self._need_result()
            n = len(self.result["strokes_mm"])
            ids = sorted({int(i) for i in ids})
            bad = [i for i in ids if not 0 <= i < n]
            if bad:
                raise SessionError(f"없는 획 번호: {bad[:10]} (0~{n - 1})")
            if not ids:
                return 0
            desc = f"획 {len(ids)}개 삭제: {ids[:20]}{' …' if len(ids) > 20 else ''}"
            self._push(desc)
            keep = [i for i in range(n) if i not in set(ids)]
            r = self.result
            self._set_strokes([r["strokes_px"][i] for i in keep], [r["strokes_mm"][i] for i in keep])
            self.edit_log.append(desc)
            return len(ids)

    def delete_region(self, region_mm, mode="inside", min_fraction=0.5):
        """종이 좌표(mm) 사각형 [x0, y0, x1, y1] 안(inside) 또는 밖(outside)의 획 삭제.
        획의 점 중 min_fraction 이상이 해당 쪽에 있으면 지움."""
        if mode not in ("inside", "outside"):
            raise SessionError("mode는 inside 또는 outside")
        x0, y0, x1, y1 = [float(v) for v in region_mm]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        with self.lock:
            self._need_result()
            ids = []
            for i, s in enumerate(self.result["strokes_mm"]):
                s = np.asarray(s)
                inside = (s[:, 0] >= x0) & (s[:, 0] <= x1) & (s[:, 1] >= y0) & (s[:, 1] <= y1)
                frac = inside.mean() if mode == "inside" else 1 - inside.mean()
                if frac >= min_fraction:
                    ids.append(i)
            if not ids:
                return 0
            count = self.delete_strokes(ids)
            self.edit_log[-1] = f"영역 {mode} 삭제 [{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}]mm: 획 {count}개"
            self.history[-1] = self.history[-1][:2] + (self.edit_log[-1],)
            return count

    def undo(self):
        with self.lock:
            if not self.history:
                return None
            px, mm, desc = self.history.pop()
            self._set_strokes(px, mm)
            if self.edit_log:
                self.edit_log.pop()
            return desc

    # ------------------------------------------------------------ 시뮬레이션
    def simulate(self):
        from . import mirobot_sim as ms

        with self.lock:
            self._need_result()
            strokes = [[tuple(pt) for pt in s] for s in self.result["strokes_mm"]]
        res = ms.simulate(ms.plan_targets(strokes, self.cfg))
        j = int(np.argmin(res["min_margin_deg"]))
        summary = {"verdict": ms.verdict(res), "min_margin_deg": round(float(res["min_margin_deg"][j]), 1),
                   "axis": ms.CONTROLLER_AXES[j], "samples": len(res["samples"])}
        with self.lock:
            self.sim = {"summary": summary, "raw": res}
        return summary

    # ------------------------------------------------------------ 상태·그림
    def state(self):
        with self.lock:
            s = {"image": self.image_path, "image_type": self.image_type, "detail": self.detail,
                 "params": dict(self.params),
                 "executor_limit_mm": self.cfg["limits"]["max_abs_paper_x_mm"] * 2,
                 "pending_limit_mm": self.cfg["limits_pending_verification"]["max_abs_paper_x_mm"] * 2}
            s["stages"] = [{"id": st.id, "label": st.label, "params": {p.key: self.params[p.key] for p in st.params}}
                           for st in stages.ALL_STAGES]
            if self.result:
                t, pl = self.result["timing"], self.result["placement"]
                s["result"] = {
                    "strokes": t["stroke_count"], "commands": t["command_count"],
                    "drawing_mm": [pl["drawing_width_mm"], pl["drawing_height_mm"]],
                    "pen_down_mm": t["pen_down_mm"], "pen_up_mm": t["pen_up_mm"],
                    "estimated_minutes": round(t["total_s"] / 60, 1),
                    "out_of_executor_limits": self.result["out_of_limits"] > 0,
                    "edits": list(self.edit_log),
                }
            s["simulation"] = self.sim["summary"] if self.sim else None
            return s

    def render(self, kind, region_mm=None, numbered=False, max_px=1000):
        """에이전트·화면용 그림 (BGR). kind: original | 단계 id | edit | lines | strokes | paper"""
        with self.lock:
            if kind == "original":
                if not self.image_path:
                    raise SessionError("이미지가 없습니다.")
                return self.color.copy()
            self._need_result()
            r = self.result
            if kind in stages.PIPELINE_IDS:
                return stages.STAGE_BY_ID[kind].preview(r["stages"][kind])
            if kind == "lines":
                return stages.STAGE_BY_ID["edges"].preview(r["stages"]["edges"])
            if kind == "edit":
                return stages.draw_strokes_colored(r["strokes_px"], r["base"].shape)
            if kind == "paper":
                return r["paper"].copy()
            if kind == "strokes":
                return render_strokes_view(r["strokes_mm"], region_mm, numbered, max_px)
        kinds = ", ".join(("original", *stages.PIPELINE_IDS, "edit", "lines", "strokes", "paper"))
        raise SessionError(f"알 수 없는 그림 종류: {kind} ({kinds})")


def render_strokes_view(strokes_mm, region_mm=None, numbered=True, max_px=1000):
    """획을 종이 좌표로 그린 확대 그림. numbered면 획마다 번호(에이전트가 삭제할 번호를 고를 때).
    region_mm가 없으면 그림 전체 범위. 격자선은 10mm 간격(좌표 읽기용)."""
    pts = np.vstack([np.asarray(s) for s in strokes_mm])
    if region_mm is None:
        (x0, y0), (x1, y1) = pts.min(axis=0) - 3, pts.max(axis=0) + 3
    else:
        x0, y0, x1, y1 = [float(v) for v in region_mm]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
    w_mm, h_mm = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    scale = max_px / max(w_mm, h_mm)
    w, h = int(w_mm * scale), int(h_mm * scale)
    img = np.full((h, w, 3), 255, np.uint8)

    def px(x, y):
        return int(round((x - x0) * scale)), int(round((y1 - y) * scale))

    for g in range(int(np.ceil(x0 / 10)) * 10, int(x1) + 1, 10):
        cv2.line(img, px(g, y0), px(g, y1), (235, 235, 235), 1)
        cv2.putText(img, str(g), (px(g, y0)[0] + 2, h - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (170, 170, 170), 1)
    for g in range(int(np.ceil(y0 / 10)) * 10, int(y1) + 1, 10):
        cv2.line(img, px(x0, g), px(x1, g), (235, 235, 235), 1)
        cv2.putText(img, str(g), (2, px(x0, g)[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (170, 170, 170), 1)
    for i, s in enumerate(strokes_mm):
        a = np.array([px(x, y) for x, y in np.asarray(s)], np.int32).reshape(-1, 1, 2)
        cv2.polylines(img, [a], False, (60, 60, 60), 1, cv2.LINE_AA)
    if numbered:
        for i, s in enumerate(strokes_mm):
            s = np.asarray(s)
            mx, my = s[len(s) // 2]
            if not (x0 <= mx <= x1 and y0 <= my <= y1):
                continue
            x, y = px(mx, my)
            cv2.putText(img, str(i), (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 3, cv2.LINE_AA)
            cv2.putText(img, str(i), (x + 2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (30, 30, 220), 1, cv2.LINE_AA)
    return img
