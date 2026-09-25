"""
단계별 선 추출 파이프라인
=========================
원본 → 전처리 → 선 검출 → 뼈대·획 → 겹침 제거 → 이어 붙이기 → 단순화
각 단계는 조절 항목(ParamSpec), 계산(run), 미리보기(preview)를 가집니다. GUI의 조절 칸과
에이전트 도구 설명은 이 정의에서 만들어집니다. Pipeline은 단계별 결과를 캐시해 두고
설정이 바뀐 첫 단계부터만 다시 계산합니다. (편집·순서·종이 배치는 session.py가 이어서 처리)
"""

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from . import presets
from . import sketch_pipeline as sp


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: str                 # "int" | "float" | "bool" | "choice"
    default: object
    lo: float = 0
    hi: float = 0
    step: float = 1
    choices: tuple = ()       # choice: ((값, 화면 이름), ...)
    help: str = ""
    odd: bool = False         # 커널 크기처럼 홀수만

    def clamp(self, value):
        """범위 밖이면 잘라서, 종류에 맞게 바꿔 돌려줌. 선택지가 틀리면 ValueError."""
        if self.kind == "bool":
            return bool(value)
        if self.kind == "choice":
            keys = [c[0] for c in self.choices]
            if value not in keys:
                raise ValueError(f"{self.key}는 {', '.join(keys)} 중 하나여야 합니다")
            return value
        v = min(max(float(value), self.lo), self.hi)
        if self.kind == "int":
            v = int(round(v))
            if self.odd and v % 2 == 0:
                v = v + 1 if v < self.hi else v - 1
            return v
        return round(round(v / self.step) * self.step, 4)


@dataclass(frozen=True)
class Stage:
    id: str
    label: str
    params: tuple
    run: Callable = None      # run(prev: dict, p: dict) -> dict (prev를 이어받아 새 값을 더함)
    preview: Callable = None  # preview(out: dict) -> BGR 이미지 (입력과 같은 크기)


class StaleRun(Exception):
    """더 새로운 설정이 들어와 이 계산이 필요 없어짐."""


# ---------------------------------------------------------------- 그리기 도우미
def _odd(k):
    k = int(k)
    return k if k % 2 == 1 else k + 1


def _bgr(gray):
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def draw_strokes_colored(strokes, shape, faded=()):
    """획마다 다른 색. faded(버린 조각)는 연회색으로 먼저 그림."""
    img = np.full((*shape[:2], 3), 255, np.uint8)
    for s, _ in faded:
        cv2.polylines(img, [np.round(s).astype(np.int32).reshape(-1, 1, 2)], False, (205, 205, 205), 1)
    for i, s in enumerate(strokes):
        hue = (i * 37) % 180
        c = cv2.cvtColor(np.uint8([[[hue, 200, 170]]]), cv2.COLOR_HSV2BGR)[0, 0].tolist()
        cv2.polylines(img, [np.round(s).astype(np.int32).reshape(-1, 1, 2)], False, c, 1, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------- 단계 계산
def _run_source(prev, p):
    return dict(prev)   # 배경 제거(rembg)는 세션이 입력 이미지를 고를 때 반영


def _run_prep(prev, p):
    gray, color = prev["gray"], prev["color"]
    if p["median_ksize"] > 1:
        k = _odd(p["median_ksize"])
        gray, color = cv2.medianBlur(gray, k), cv2.medianBlur(color, k)
    if p["blur_ksize"] > 1:
        k = _odd(p["blur_ksize"])
        gray, color = cv2.GaussianBlur(gray, (k, k), 0), cv2.GaussianBlur(color, (k, k), 0)
    return {**prev, "prep_gray": gray, "prep_color": color}


def _run_edges(prev, p):
    # 블러는 전처리에서 했으므로 여기서는 1(끔)
    if p["edge_mode"] == "dark":
        e = sp.compute_dark_mask(prev["prep_gray"], 1)
    elif p["edge_mode"] == "lab":
        e = sp.compute_edges_lab(prev["prep_color"], p["canny_low"], p["canny_high"], 1)
    else:
        e = sp.compute_edges(prev["prep_gray"], p["canny_low"], p["canny_high"], 1)
    return {**prev, "edges": e}


def _run_trace(prev, p):
    disc = []
    st = sp.trace_strokes(prev["edges"], p["min_length_px"], p["spur_px"], discarded=disc)
    return {**prev, "strokes": st, "discarded_trace": disc}


def _run_dedupe(prev, p):
    if not p["dedupe_px"]:
        return {**prev, "discarded_dedupe": []}
    disc = []
    st = sp.dedupe_strokes(prev["strokes"], prev["edges"].shape, int(p["dedupe_px"]), discarded=disc)
    return {**prev, "strokes": st, "discarded_dedupe": disc}


def _run_merge(prev, p):
    if not p["merge_join_px"]:
        return dict(prev)
    return {**prev, "strokes": sp.merge_strokes(prev["strokes"], p["merge_join_px"])}


def _run_simplify(prev, p):
    return {**prev, "strokes": sp.simplify_strokes(prev["strokes"], p["epsilon_px"])}


EDGE_MODES = (("luma", "밝기"), ("lab", "색 차이"), ("dark", "어두운 선"))
_hi, _med = presets.DETAIL_PRESETS["high"], presets.IMAGE_TYPES["illustration"]["median"]

STAGES = (
    Stage("source", "원본", (
        ParamSpec("rembg", "배경 제거 (rembg)", "bool", False, help="첫 실행은 약 1분, 이후 캐시"),),
        _run_source, lambda o: o["color"].copy()),
    Stage("prep", "전처리", (
        ParamSpec("median_ksize", "미디언 (px, 망점 제거)", "int", _med, 0, 15,
                  help="만화 스크린톤을 지움. 0 = 끔, 만화는 11 정도"),
        ParamSpec("blur_ksize", "가우시안 블러 (px)", "int", 5, 1, 15, odd=True,
                  help="클수록 잔선이 줄고 윤곽이 부드러워짐")),
        _run_prep, lambda o: _bgr(o["prep_gray"])),
    Stage("edges", "선 검출", (
        ParamSpec("edge_mode", "방식", "choice", "luma", choices=EDGE_MODES,
                  help="밝기=흑백 Canny, 색 차이=Lab Canny(밝기가 같은 색 경계도 찾음), 어두운 선=선화 중심선"),
        ParamSpec("canny_low", "Canny 하한", "int", _hi[0], 0, 255, help="낮을수록 약한 선도 잡음"),
        ParamSpec("canny_high", "Canny 상한", "int", _hi[1], 0, 400, help="선이 시작되는 강한 경계 기준")),
        _run_edges, lambda o: _bgr(255 - o["edges"])),
    Stage("trace", "뼈대·획", (
        ParamSpec("min_length_px", "최소 덩어리 (px)", "int", _hi[2], 1, 100, help="이보다 작은 선 덩어리는 버림"),
        ParamSpec("spur_px", "잔가지 길이 (px)", "int", 6, 0, 20, help="분기점에 붙은 이보다 짧은 가지는 버림")),
        _run_trace, lambda o: draw_strokes_colored(o["strokes"], o["gray"].shape, o["discarded_trace"])),
    Stage("dedupe", "겹침 제거", (
        ParamSpec("dedupe_px", "이중선 거리 (px, 0=끔)", "int", presets.DEFAULT_DEDUPE_PX, 0, 8,
                  help="이 거리 안에서 겹치는 선은 하나만 남김"),),
        _run_dedupe, lambda o: draw_strokes_colored(o["strokes"], o["gray"].shape, o["discarded_dedupe"])),
    Stage("merge", "이어 붙이기", (
        ParamSpec("merge_join_px", "연결 거리 (px, 0=끔)", "float", presets.DEFAULT_MERGE_JOIN_PX, 0, 8, 0.5,
                  help="끝점이 이 거리 안이면 펜을 떼지 않고 이어 그림"),),
        _run_merge, lambda o: draw_strokes_colored(o["strokes"], o["gray"].shape)),
    Stage("simplify", "단순화", (
        ParamSpec("epsilon_px", "단순화 오차 (px)", "float", _hi[3], 0.5, 5.0, 0.1,
                  help="클수록 점·명령 수가 줄지만 곡선이 거칠어짐"),),
        _run_simplify, lambda o: draw_strokes_colored(o["strokes"], o["gray"].shape)),
)
ALL_STAGES = STAGES + (
    Stage("edit", "편집", ()),
    Stage("paper", "순서·종이", (
        ParamSpec("box_mm", "그리기 크기 (mm, 긴 변)", "int", 100, 30, 120, help="실행기 허용 범위는 설정 파일 기준"),)),
)
PIPELINE_IDS = tuple(s.id for s in STAGES)
STAGE_BY_ID = {s.id: s for s in ALL_STAGES}
PARAM_SPECS = {p.key: p for s in ALL_STAGES for p in s.params}


def default_params():
    return {k: s.default for k, s in PARAM_SPECS.items()}


def candidates_of(outputs):
    """버린 조각 전부: [(점 배열, 이유)]."""
    last = outputs["simplify"]
    return list(last.get("discarded_trace", [])) + list(last.get("discarded_dedupe", []))


class Pipeline:
    """단계별 결과 캐시. 단계 k의 키 = (단계 k-1의 키, 단계 id, 단계 설정)."""

    def __init__(self, stages=STAGES):
        self.stages = stages
        self._cache = {}                              # stage id -> (key, output)
        self.run_counts = {s.id: 0 for s in stages}

    @staticmethod
    def _stage_params(stage, params):
        return {spec.key: params[spec.key] for spec in stage.params}

    def _keys(self, input_key, params):
        key = ("input", input_key)
        for st in self.stages:
            p = self._stage_params(st, params)
            key = (key, st.id, tuple(sorted(p.items())))
            yield st, p, key

    def run(self, inputs, input_key, params, is_current=lambda: True):
        prev, outputs = inputs, {}
        for st, p, key in self._keys(input_key, params):
            hit = self._cache.get(st.id)
            if hit is not None and hit[0] == key:
                out = hit[1]
            else:
                if not is_current():
                    raise StaleRun()
                out = st.run(prev, p)
                self.run_counts[st.id] += 1
                self._cache[st.id] = (key, out)
            outputs[st.id] = out
            prev = out
        return outputs

    def dirty_from(self, input_key, params):
        """다시 계산해야 하는 첫 단계 id. 전부 캐시에 있으면 None."""
        for st, _, key in self._keys(input_key, params):
            hit = self._cache.get(st.id)
            if hit is None or hit[0] != key:
                return st.id
        return None
