# 단계별 선 추출 파이프라인과 편집 제안 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선 추출을 캐시되는 단계 파이프라인으로 바꿔 단계별로 보고 조정할 수 있게 하고, LLM 에이전트가 번호로 선을 살리기·지우기·점 편집을 제안(초록/빨강)하고 적용할 수 있게 한다.

**Architecture:**
- **`stages.py`:** 단계 정의(`ParamSpec`/`Stage`)와 해시 캐시 `Pipeline`을 둔다. 기존 `sketch_pipeline.py` 함수들을 단계로 감싼다.
- **`edits.py`:** 순수 기하 편집 함수, 모양 기반 재적용, 에이전트용 초록/빨강 렌더링을 둔다.
- **`session.py`:** 파이프라인 결과로 번호표를 만들고, 제안·적용·되돌리기를 관리한다.
- **GUI:** `stage_view.py`의 단계 띠·큰 보기·제안 바를 쓴다. 에이전트 도구는 단계 정의에서 스키마를 만든다.

**Tech Stack:** Python 3.11+, OpenCV 4.x, NumPy, scikit-image, CustomTkinter, matplotlib(TkAgg), unittest

**Spec:** `docs/superpowers/specs/2026-09-26-stage-pipeline-edit-proposals-design.md`

## Global Constraints

- **테스트 실행:** `python -m unittest discover -s tests`. 모든 작업 끝에 전체가 통과하고 `python -m pyflakes mirobot_sketch tests`가 깨끗해야 한다.
- **코드 스타일:** 주석과 docstring은 한국어, 들여쓰기 4칸, 한 줄 120자 이하로 기존 코드와 맞춘다.
- **이미지 규칙:** 처리 이미지는 긴 변 800px(`sp.DEFAULT_MAX_SIDE`)이고, 흑백(`gray`)과 컬러(`color`, BGR)는 같은 크기다.
- **좌표 규칙:**
  - 종이 좌표는 mm, 원점은 종이 중심, x는 오른쪽 +, y는 위쪽 +다.
  - 편집 기록은 이미지 px로 저장한다.
  - 에이전트의 mm 입력은 `|x| ≤ 60`, `|y| ≤ 60`(`limits_pending_verification`)을 넘으면 거부한다.
- **도구 규칙:** 도구는 로봇을 움직이거나 파일을 쓰지 않는다. `AgentToolbox.call`은 예외를 던지지 않고 `(parts, is_error)`를 돌려준다.
- **편집 한도:**
  - 한 번 호출에 편집은 최대 200개(`edits.MAX_OPS`)다.
  - `add_stroke`는 2~200점이다.
  - `get_stroke`는 최대 400점을 돌려준다.
- **같은 선 판정:** 다시 계산할 때 획 점의 60%(`MATCH_FRACTION`) 이상이 지운 모양의 2px(`MATCH_TOL_PX`) 안에 들면 같은 선으로 보고 다시 지운다.
- **색:** 초록 = 새로 생길 모양, 빨강 = 사라질 모양. BGR 값은 `GREEN = (40, 160, 40)`, `RED = (40, 40, 220)`이다.
- **자동 재계산 지연:** 0.3초(`RECOMPUTE_DELAY_MS = 300`)다.
- **커밋:** 커밋 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` 줄을 넣는다. 작업은 `feature/stage-pipeline` 브랜치에서 한다(Task 0).

## Spec 수정 (계획 단계에서 정함)

- **설계 §4 마지막 줄 변경:** "다시 계산할 때 제안 모양 유지·번호만 새로"를 다음으로 바꾼다. **파이프라인 결과가 바뀌어 다시 계산하면, 적용 전 제안은 취소하고 "제안 n건을 취소했습니다"를 알린다.** 적용된 편집은 모양 기록으로 유지한다. 종이 크기(`box_mm`)만 바뀐 경우처럼 파이프라인 결과가 그대로면 제안과 번호를 그대로 둔다.
  - 이유: 제안의 대상 번호가 바뀐 결과에 다시 들어맞는지 판정하는 기준을 만들면, 적용된 편집 재적용과 규칙이 겹친다(YAGNI).
- **설계 §3 번호 규칙 구체화:**
  - 지운 획은 같은 번호의 "후보(deleted)"가 된다. 그래서 같은 번호로 다시 살릴 수 있다.
  - `join`으로 사라진 획은 `gone` 상태가 된다.
- **`join`·`split` 묶음:** 이 두 편집이 만든 제안은 **묶음**이다. `exclude`·`only`로 묶음의 일부만 고르면 그 묶음 전체를 적용하지 않고 결과에 알린다.
- Task 13에서 spec 문서에 이 세 줄을 반영한다.

## Review Focus

1. **후보가 수천 개인 사진:** 번호 딱지와 `list_strokes`가 느려지거나 화면을 덮지 않아야 한다. 딱지는 최대 400개, 표는 최대 300줄에 "잘림" 안내를 붙인다. → Task 9, Task 12 테스트
2. **제안이 남은 상태에서 슬라이더를 움직여 다시 계산:** 적용된 편집은 남고, 제안은 취소되며 알림이 떠야 한다. → Task 9 테스트
3. **에이전트가 범위 밖 mm 좌표, 없는 번호, 후보 번호로 삭제, 점 번호 초과를 보낼 때:** 무엇이 틀렸는지 적힌 오류를 돌려주고, 상태는 하나도 바뀌지 않아야 한다(원자성). → Task 9 테스트
4. **모든 획을 지우는 적용:** 거부해야 한다(드로잉에는 획 1개 이상 필요). → Task 9 테스트
5. **아주 작은 이미지나 투명 PNG:** 모든 단계 미리보기가 같은 크기로 나오고 오류가 없어야 한다. → Task 5 테스트

---

### Task 0: 작업 브랜치 준비

**Files:** 없음(git만)

- [ ] **Step 1: 브랜치 만들기**

```bash
git switch -c feature/stage-pipeline
```

- [ ] **Step 2: 이전 작업을 따로 커밋 (사용자가 커밋을 승인한 경우에만)**

이전 대화의 작업(에이전트 패널, 로그인 수정, RViz 버튼, 컬러 원본)이 아직 커밋되지 않았다. 사용자가 승인하면 이 브랜치의 첫 커밋으로 남기고, 승인하지 않으면 이 단계는 건너뛴다.

```bash
git add -A
git commit -m "Agent side panel, CLI login fixes, GUI RViz launch, color original preview

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 1a — 단계별 파이프라인

### Task 1: 리팩터링 전 기준값 저장

**Files:**
- Create: `tests/golden.py`
- Create: `tests/test_golden.py`
- Create: `tests/data/pipeline_golden.json` (생성물)

**Interfaces:**
- Produces:
  - `golden.signature(strokes) -> {"count": int, "total_px": float, "sha1": str}`
  - `golden.compute_all(include_samples=True) -> {"synthetic": {...}, "samples": {...}}`
  - `golden.synthetic_images() -> {"line": ndarray, "shade": ndarray}`
  - `golden.GOLDEN: Path`

- [ ] **Step 1: 기준값 모듈 작성**

```python
# tests/golden.py
"""리팩터링 전후 run_pipeline() 결과 비교용 기준값 (tests/data/pipeline_golden.json)

    python tests/golden.py --write     # 리팩터링 전에 한 번 실행해 기준값 저장
    python tests/golden.py --perf      # 샘플 이미지 단계별 시간 측정 (Task 13)
합성 이미지 기준값은 CI에서도 비교하고, 샘플(input/, 저장소 밖)은 있을 때만 비교한다.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mirobot_sketch import presets  # noqa: E402
from mirobot_sketch import sketch_pipeline as sp  # noqa: E402

GOLDEN = ROOT / "tests" / "data" / "pipeline_golden.json"
SAMPLE_TYPES = {"illust1_color.jpg": "illustration", "illust2_color.jpg": "illustration",
                "illust3_manga.jpg": "manga", "photo1_mic.webp": "photo",
                "photo2_stage.jpg": "photo", "photo3_chair.jpg": "photo"}


def synthetic_images():
    """선화(사각형·원·잡음 점)와 면으로 된 도형(명암·글씨)."""
    line = np.full((400, 400), 255, np.uint8)
    cv2.rectangle(line, (80, 80), (320, 320), 0, 3)
    cv2.circle(line, (200, 200), 60, 0, 3)
    for x in range(20, 60, 12):
        cv2.line(line, (x, 20), (x + 6, 30), 0, 2)
    shade = np.full((300, 420), 230, np.uint8)
    cv2.circle(shade, (140, 150), 90, 90, -1)
    cv2.rectangle(shade, (230, 60), (380, 240), 160, -1)
    cv2.putText(shade, "Hi", (250, 170), cv2.FONT_HERSHEY_SIMPLEX, 2.5, 40, 6)
    return {"line": sp.resize_max_side(line), "shade": sp.resize_max_side(shade)}


def cases_for(image_type):
    """이미지 종류 프리셋 × 상세도(high, medium) × 선 후보(canny, dark). rembg는 끔."""
    t = presets.IMAGE_TYPES[image_type]
    out = []
    for detail in ("high", "medium"):
        lo, hi, ml, eps = presets.DETAIL_PRESETS[detail]
        for src in ("canny", "dark"):
            out.append({"canny_low": lo, "canny_high": hi, "blur_ksize": 5, "min_length_px": ml,
                        "epsilon_px": eps, "method": "skeleton", "line_source": src,
                        "median_ksize": t["median"], "merge_join_px": presets.DEFAULT_MERGE_JOIN_PX,
                        "dedupe_px": presets.DEFAULT_DEDUPE_PX})
    return out


def sample_cases(image_type):
    c = cases_for(image_type)
    return [c[0], c[3]]   # high+canny, medium+dark (샘플 1장에 2가지만: 시간 절약)


def signature(strokes):
    h = hashlib.sha1()
    total = 0.0
    for s in strokes:
        a = np.round(np.asarray(s, dtype=np.float64), 2)
        if len(a) > 1:
            total += float(np.hypot(*np.diff(a, axis=0).T).sum())
        h.update(a.tobytes())
        h.update(b"|")
    return {"count": len(strokes), "total_px": round(total, 1), "sha1": h.hexdigest()}


def compute_all(include_samples=True):
    out = {"synthetic": {}, "samples": {}}
    for name, img in synthetic_images().items():
        for i, c in enumerate(cases_for("illustration") + cases_for("manga")):
            out["synthetic"][f"{name}#{i}"] = signature(sp.run_pipeline(img, **c)[1])
    if include_samples:
        for fname, typ in SAMPLE_TYPES.items():
            p = ROOT / "input" / fname
            if not p.exists():
                continue
            gray = sp.load_gray(p)
            for i, c in enumerate(sample_cases(typ)):
                out["samples"][f"{fname}#{i}"] = signature(sp.run_pipeline(gray, **c)[1])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="기준값 저장")
    ap.add_argument("--perf", action="store_true", help="샘플 단계별 시간 (Task 13에서 추가)")
    args = ap.parse_args()
    if args.write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        data = compute_all()
        GOLDEN.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"저장: {GOLDEN} (합성 {len(data['synthetic'])}, 샘플 {len(data['samples'])})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 비교 테스트 작성**

```python
# tests/test_golden.py
"""리팩터링 전후 run_pipeline() 결과가 같은지 (기준값: tests/golden.py --write)."""

import json
import unittest

import golden


class GoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not golden.GOLDEN.exists():
            raise unittest.SkipTest("기준값 없음: python tests/golden.py --write")
        cls.expected = json.loads(golden.GOLDEN.read_text(encoding="utf-8"))

    def test_synthetic_same_as_before_refactor(self):
        got = golden.compute_all(include_samples=False)["synthetic"]
        self.assertEqual(got, self.expected["synthetic"])

    def test_samples_same_as_before_refactor(self):
        exp = self.expected.get("samples") or {}
        if not exp or not (golden.ROOT / "input").exists():
            self.skipTest("샘플 이미지 없음 (input/은 저장소 밖)")
        got = golden.compute_all()["samples"]
        for k, v in exp.items():
            if k in got:
                self.assertEqual(got[k], v, k)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 기준값 생성 (리팩터링 전 코드로)**

Run: `python tests/golden.py --write`
Expected: `저장: ...pipeline_golden.json (합성 16, 샘플 12)` — 샘플 수는 input/에 있는 이미지 수 × 2

- [ ] **Step 4: 비교 테스트 통과 확인**

Run: `python -m unittest tests.test_golden -v` (tests 폴더에서: `cd tests && python -m unittest test_golden -v`)
Expected: 2 tests OK

- [ ] **Step 5: 커밋**

```bash
git add tests/golden.py tests/test_golden.py tests/data/pipeline_golden.json
git commit -m "Record run_pipeline golden signatures before stage refactor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 색 차이(Lab) 선 검출

**Files:**
- Modify: `mirobot_sketch/sketch_pipeline.py` (`compute_dark_mask` 아래에 함수 추가)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `sp.compute_edges_lab(bgr_img, canny_low=50, canny_high=150, blur_ksize=5) -> uint8 이진 이미지 (0/255)`
  - `sp.LAB_AB_GAIN = 2.0`

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_pipeline.py` 끝, `if __name__` 위)

```python
class LabEdgesTest(unittest.TestCase):
    def test_lab_finds_boundary_between_colors_of_equal_brightness(self):
        # 흑백으로 바꾸면 밝기가 같은 두 색(주황빛 / 청록빛): 흑백 Canny는 경계를 못 찾음
        img = np.zeros((200, 200, 3), np.uint8)
        img[:, :100] = (0, 100, 200)     # BGR, 흑백 ≈ 118.5
        img[:, 100:] = (255, 152, 0)     # BGR, 흑백 ≈ 118.3
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        luma = sp.compute_edges(gray, 30, 100, 5)
        lab = sp.compute_edges_lab(img, 30, 100, 5)
        self.assertLess(int((luma > 0).sum()), 20)
        self.assertGreater(int((lab[:, 90:110] > 0).sum()), 150)   # 세로 경계 200px 대부분

    def test_lab_on_gray_image_matches_brightness_edges_roughly(self):
        img = np.full((200, 200), 255, np.uint8)
        cv2.circle(img, (100, 100), 50, 0, 3)
        bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        a = (sp.compute_edges(img, 30, 100, 5) > 0).sum()
        b = (sp.compute_edges_lab(bgr, 30, 100, 5) > 0).sum()
        self.assertLess(abs(int(a) - int(b)), 0.3 * a)
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_pipeline.LabEdgesTest -v`
Expected: FAIL — `AttributeError: module 'mirobot_sketch.sketch_pipeline' has no attribute 'compute_edges_lab'`

- [ ] **Step 3: 구현** (`compute_dark_mask` 함수 바로 아래)

```python
LAB_AB_GAIN = 2.0  # a·b 채널은 값 범위가 좁아(128 중심) 대비를 늘려 같은 임계값을 씀


def compute_edges_lab(bgr_img, canny_low=50, canny_high=150, blur_ksize=5):
    """색 차이 선 검출: Lab의 L·a·b 채널마다 Canny를 적용해 합칩니다.

    흑백 변환은 밝기가 비슷한 두 색(예: 주황 배경과 머리카락)의 경계를 지워 버립니다.
    a(초록↔빨강)·b(파랑↔노랑) 채널은 밝기가 같아도 색이 다르면 값이 달라 경계가 남습니다.
    """
    k = int(blur_ksize)
    k = k if k % 2 == 1 else k + 1
    lab = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2LAB)
    out = np.zeros(bgr_img.shape[:2], np.uint8)
    for c in range(3):
        ch = lab[:, :, c]
        if c > 0:
            ch = np.clip(128 + (ch.astype(np.float32) - 128) * LAB_AB_GAIN, 0, 255).astype(np.uint8)
        if k > 1:
            ch = cv2.GaussianBlur(ch, (k, k), 0)
        out |= cv2.Canny(ch, float(canny_low), float(canny_high))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `cd tests && python -m unittest test_pipeline -v`
Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add mirobot_sketch/sketch_pipeline.py tests/test_pipeline.py
git commit -m "Add Lab color-difference edge detection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 버린 조각 기록 (살릴 선 후보의 출처)

**Files:**
- Modify: `mirobot_sketch/sketch_pipeline.py` (`trace_strokes`, `dedupe_strokes`)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `sp.trace_strokes(edges, min_length_px=15, spur_px=6, discarded=None)`: `discarded`가 list면 `(points (N,2) int, "small"|"spur")`를 추가한다.
  - `sp.dedupe_strokes(strokes, shape, dist_px=4, min_keep_px=8, overlap_px=2, discarded=None)`: `(points, "overlap")`를 추가한다.
  - 반환값은 `discarded` 유무와 상관없이 기존과 같다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
class DiscardedTest(unittest.TestCase):
    def test_trace_records_small_blobs_and_spurs(self):
        img = np.zeros((200, 200), np.uint8)
        cv2.circle(img, (100, 100), 50, 255, 1)
        cv2.line(img, (10, 10), (13, 10), 255, 1)          # 4px 덩어리 -> small
        cv2.line(img, (150, 100), (154, 100), 255, 1)      # 원에 붙은 5px 잔가지 -> spur
        disc = []
        kept = sp.trace_strokes(img, min_length_px=15, spur_px=6, discarded=disc)
        reasons = {r for _, r in disc}
        self.assertIn("small", reasons)
        self.assertIn("spur", reasons)
        self.assertEqual([s.tolist() for s in sp.trace_strokes(img, 15, 6)],
                         [s.tolist() for s in kept])            # 기록해도 결과는 같음

    def test_dedupe_records_overlap_pieces(self):
        a = np.array([[10, 50], [190, 50]])
        b = np.array([[10, 52], [190, 52]])               # 2px 옆 이중선
        disc = []
        out = sp.dedupe_strokes([a, b], (100, 200), 4, discarded=disc)
        self.assertTrue(disc)
        self.assertEqual({r for _, r in disc}, {"overlap"})
        plain = sp.dedupe_strokes([a, b], (100, 200), 4)
        self.assertEqual([p.tolist() for p in out], [p.tolist() for p in plain])
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_pipeline.DiscardedTest -v`
Expected: FAIL — `TypeError: trace_strokes() got an unexpected keyword argument 'discarded'`

- [ ] **Step 3: 구현**

`trace_strokes`의 시그니처와 앞부분·잔가지 부분을 바꾼다.

```python
def trace_strokes(edges, min_length_px=15, spur_px=6, discarded=None):
    """... (기존 docstring 유지) ...
    discarded가 list면 버린 조각을 (점 배열, 이유)로 추가합니다: "small"(작은 덩어리), "spur"(잔가지).
    """
    skel = skeletonize_edges(edges)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(skel.astype(np.uint8), connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_length_px
    keep[0] = False  # 배경
    kept = keep[labels]
    if discarded is not None:
        for s in trace_skeleton(skel & ~kept):
            if len(s) >= 2:
                discarded.append((np.asarray(s), "small"))
    skel = kept

    deg = neighbor_count(skel)
    out = []
    for s in trace_skeleton(skel):
        length = polyline_length(s)
        if length < 2:
            continue
        if not is_closed(s):
            end_a = deg[s[0][1], s[0][0]] == 1
            end_b = deg[s[-1][1], s[-1][0]] == 1
            if end_a != end_b and length < spur_px:
                if discarded is not None:
                    discarded.append((np.asarray(s), "spur"))
                continue
        out.append(s)
    return out
```

`dedupe_strokes`의 시그니처에 `discarded=None`을 더하고, 획마다 "남길 구간" 반복(`k = 0; while k < n: ...`) 바로 뒤에 아래를 넣는다.

```python
        if discarded is not None:
            k = 0
            while k < n:
                if free[k]:
                    k += 1
                    continue
                j = k
                while j < n and not free[j]:
                    j += 1
                if j - k >= 2:
                    discarded.append((pts[k:j], "overlap"))
                k = j
```

docstring 끝에 `discarded가 list면 겹쳐서 빠진 구간을 (점 배열, "overlap")으로 추가합니다.`를 적는다.

- [ ] **Step 4: 통과 확인 (기준값 포함)**

Run: `python -m unittest discover -s tests`
Expected: OK (`test_golden` 포함 — 결과가 바뀌지 않았음)

- [ ] **Step 5: 커밋**

```bash
git add mirobot_sketch/sketch_pipeline.py tests/test_pipeline.py
git commit -m "Record discarded pieces (small, spur, overlap) as restore candidates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `stages.py` — 단계 정의와 캐시 파이프라인

**Files:**
- Create: `mirobot_sketch/stages.py`
- Modify: `mirobot_sketch/sketch_pipeline.py` (`run_pipeline`의 skeleton 경로를 Pipeline으로 위임)
- Test: `tests/test_stages.py`

**Interfaces:**
- Consumes:
  - `sp.compute_edges`, `sp.compute_dark_mask`, `sp.compute_edges_lab`
  - `sp.trace_strokes(..., discarded=)`, `sp.dedupe_strokes(..., discarded=)`
  - `sp.merge_strokes`, `sp.simplify_strokes`
- Produces:
  - `ParamSpec(key, label, kind, default, lo=0, hi=0, step=1, choices=(), help="", odd=False)`와 `.clamp(v)`. 잘못된 선택지는 `ValueError`를 던진다.
  - `Stage(id, label, params, run=None, preview=None)`
  - 단계 모음:
    - `STAGES`: 파이프라인 7단계 tuple (`source, prep, edges, trace, dedupe, merge, simplify`)
    - `ALL_STAGES`: `STAGES + (edit, paper)`
    - `PIPELINE_IDS`, `STAGE_BY_ID`, `PARAM_SPECS: {key: ParamSpec}`
  - 함수:
    - `default_params() -> dict`
    - `candidates_of(outputs) -> [(points, reason)]`
    - `draw_strokes_colored(strokes, shape, faded=()) -> BGR`
  - `StaleRun(Exception)`
  - `Pipeline()`:
    - `.run(inputs, input_key, params, is_current=lambda: True) -> {stage_id: output}`
    - `.dirty_from(input_key, params) -> stage_id | None`
    - `.run_counts: {stage_id: int}`
  - 단계 출력은 dict이고, 앞 단계 값을 복사해 이어받는다.
    - 공통 키: `gray`, `color`
    - `prep` 이후: `prep_gray`, `prep_color`
    - `edges` 이후: `edges`
    - `trace` 이후: `strokes`, `discarded_trace`
    - `dedupe` 이후: `discarded_dedupe`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_stages.py
"""단계 정의·캐시 파이프라인."""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import stages  # noqa: E402

import golden  # noqa: E402


def inputs():
    gray = golden.synthetic_images()["line"]
    return {"gray": gray, "color": cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)}


class ParamSpecTest(unittest.TestCase):
    def test_every_default_is_valid_and_keys_unique(self):
        keys = [p.key for st in stages.ALL_STAGES for p in st.params]
        self.assertEqual(len(keys), len(set(keys)))
        for spec in stages.PARAM_SPECS.values():
            self.assertEqual(spec.clamp(spec.default), spec.default, spec.key)

    def test_clamp(self):
        s = stages.PARAM_SPECS
        self.assertEqual(s["blur_ksize"].clamp(4), 5)        # 홀수로
        self.assertEqual(s["blur_ksize"].clamp(99), 15)
        self.assertEqual(s["epsilon_px"].clamp(1.2345), 1.2)
        self.assertEqual(s["canny_low"].clamp(-5), 0)
        self.assertTrue(s["rembg"].clamp(1))
        with self.assertRaises(ValueError):
            s["edge_mode"].clamp("rainbow")


class PipelineTest(unittest.TestCase):
    def test_late_change_only_recomputes_late_stages(self):
        pl, p = stages.Pipeline(), stages.default_params()
        pl.run(inputs(), "img", p)
        first = dict(pl.run_counts)
        pl.run(inputs(), "img", p)
        self.assertEqual(pl.run_counts, first)                         # 전부 캐시
        pl.run(inputs(), "img", {**p, "epsilon_px": 2.0})
        changed = {k for k in first if pl.run_counts[k] != first[k]}
        self.assertEqual(changed, {"simplify"})
        pl.run(inputs(), "img", {**p, "epsilon_px": 2.0, "canny_low": 60})
        self.assertEqual(pl.run_counts["prep"], first["prep"])
        self.assertEqual(pl.run_counts["edges"], first["edges"] + 1)
        self.assertEqual(pl.dirty_from("img", {**p, "dedupe_px": 2}), "dedupe")
        self.assertIsNone(pl.dirty_from("img", {**p, "epsilon_px": 2.0, "canny_low": 60}))

    def test_stale_run_stops_before_computing(self):
        pl = stages.Pipeline()
        with self.assertRaises(stages.StaleRun):
            pl.run(inputs(), "img", stages.default_params(), is_current=lambda: False)

    def test_previews_are_same_size_bgr(self):
        inp = inputs()
        outs = stages.Pipeline().run(inp, "img", stages.default_params())
        for sid in stages.PIPELINE_IDS:
            img = stages.STAGE_BY_ID[sid].preview(outs[sid])
            self.assertEqual(img.shape, (*inp["gray"].shape, 3), sid)
            self.assertEqual(img.dtype, np.uint8)

    def test_candidates_collected(self):
        outs = stages.Pipeline().run(inputs(), "img", stages.default_params())
        reasons = {r for _, r in stages.candidates_of(outs)}
        self.assertTrue(reasons <= {"small", "spur", "overlap"})

    def test_lab_mode_runs(self):
        p = {**stages.default_params(), "edge_mode": "lab"}
        outs = stages.Pipeline().run(inputs(), "img", p)
        self.assertTrue(outs["simplify"]["strokes"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_stages -v`
Expected: FAIL — `ImportError: cannot import name 'stages'`

- [ ] **Step 3: `stages.py` 구현**

```python
# mirobot_sketch/stages.py
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
```

- [ ] **Step 4: `run_pipeline`의 skeleton 경로를 Pipeline으로 위임**

`run_pipeline` 본문을 아래로 바꾼다(docstring 유지). contour 경로는 비교용이라 그대로 둔다.

```python
    if method == "contour":
        if median_ksize and median_ksize > 1:
            k = int(median_ksize)
            gray_img = cv2.medianBlur(gray_img, k if k % 2 == 1 else k + 1)
        edges = (compute_dark_mask(gray_img, blur_ksize) if line_source == "dark"
                 else compute_edges(gray_img, canny_low, canny_high, blur_ksize))
        raw = extract_strokes_contour(edges, min_length_px)
        return edges, order_strokes(simplify_strokes(raw, epsilon_px))

    from .stages import Pipeline, default_params   # stages가 이 모듈을 import하므로 함수 안에서

    params = {**default_params(), "median_ksize": median_ksize or 0, "blur_ksize": blur_ksize,
              "edge_mode": "dark" if line_source == "dark" else "luma",
              "canny_low": canny_low, "canny_high": canny_high, "min_length_px": min_length_px,
              "spur_px": 6, "dedupe_px": dedupe_px or 0, "merge_join_px": merge_join_px or 0,
              "epsilon_px": epsilon_px}
    color = cv2.cvtColor(gray_img, cv2.COLOR_GRAY2BGR)
    out = Pipeline().run({"gray": gray_img, "color": color}, None, params)["simplify"]
    return out["edges"], order_strokes(out["strokes"])
```

- [ ] **Step 5: 통과 확인 (기준값이 같아야 함)**

Run: `python -m unittest discover -s tests`
Expected: OK. 특히 `test_golden`이 PASS해야 한다(리팩터링 전과 결과 동일). 다르면 `_run_prep`의 블러·미디언 순서와 `_odd` 처리를 기존 `compute_edges`/`run_pipeline`과 한 줄씩 비교한다.

- [ ] **Step 6: 커밋**

```bash
git add mirobot_sketch/stages.py mirobot_sketch/sketch_pipeline.py tests/test_stages.py
git commit -m "Add stage definitions and cached Pipeline; run_pipeline delegates to it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 세션을 Pipeline으로 전환 (+ 컬러 rembg)

**Files:**
- Modify: `mirobot_sketch/sketch_pipeline.py` (`remove_background_bgr` 추가, `remove_background` 위임)
- Modify: `mirobot_sketch/paper_mapping.py:69-78` (placement에 `center_px` 추가)
- Modify: `mirobot_sketch/session.py` (설정·입력·run·render·state)
- Modify: `mirobot_sketch/gui.py` (`line_source` → `edge_mode`, `_base_cache` → `_inputs_cache`: 앱이 계속 동작하게 하는 최소 수정)
- Test: `tests/test_agent.py` (`SessionTest`)

**Interfaces:**
- Consumes: `stages.Pipeline`, `stages.PARAM_SPECS`, `stages.default_params`, `stages.StaleRun`, `stages.STAGE_BY_ID`, `stages.PIPELINE_IDS`, `stages.ALL_STAGES`
- Produces:
  - `sp.remove_background_bgr(img_path, max_side=DEFAULT_MAX_SIDE, cache_dir=None) -> BGR`
  - `placement["center_px"] = [cx, cy]`
  - 설정 관련:
    - `SketchSession.param_specs() -> {key: ParamSpec}`. `box_mm` 상한은 설정 파일의 pending 한계 × 2다.
    - `SketchSession.update_params(changes) -> applied`. `line_source`는 `edge_mode`로 바꾸고 `generation`을 올린다.
    - `SketchSession.generation: int`
  - 계산 관련:
    - `SketchSession.run() -> result | None`. `None`이면 더 새로운 설정이 들어와 계산을 버린 것이다.
    - `SketchSession.run_current(max_tries=5) -> result`
    - `SketchSession.dirty_stages() -> [stage_id...]`. 다시 계산될 단계 목록이고, 항상 `edit`, `paper`를 포함한다.
  - 보기와 상태:
    - `SketchSession.render(kind, region_mm=None, numbered=False, max_px=1000)`. kind는 `original`, `PIPELINE_IDS`의 단계, `edit`, `lines`(= edges), `strokes`, `paper`다.
    - `state()["stages"] = [{"id", "label", "params": {key: value}}]`
  - `result`에 `"stages": outputs` 키를 추가한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`SessionTest`에 추가)

```python
    def test_only_changed_stages_recompute(self):
        s = self.new_session()
        before = dict(s.pipeline.run_counts)
        s.update_params({"epsilon_px": 2.5})
        s.run()
        changed = {k for k in before if s.pipeline.run_counts[k] != before[k]}
        self.assertEqual(changed, {"simplify"})

    def test_line_source_is_mapped_to_edge_mode(self):
        s = self.new_session()
        self.assertEqual(s.update_params({"line_source": "dark"}), {"edge_mode": "dark"})
        self.assertEqual(s.update_params({"line_source": "canny"}), {"edge_mode": "luma"})
        with self.assertRaises(SessionError):
            s.update_params({"edge_mode": "rainbow"})

    def test_stale_run_returns_none(self):
        s = self.new_session()
        s.update_params({"canny_low": 70})
        real = s.pipeline.run

        def bump_then_run(*a, **k):
            s.generation += 1        # 계산 시작 직후 사용자가 값을 또 바꾼 상황
            return real(*a, **k)

        s.pipeline.run = bump_then_run
        self.assertIsNone(s.run())
        s.pipeline.run = real
        self.assertIsNotNone(s.run_current())

    def test_every_stage_renders_same_size_even_for_tiny_transparent_png(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.png"
            img = np.zeros((60, 90, 4), np.uint8)
            cv2.circle(img, (45, 30), 20, (0, 0, 0, 255), 2)   # 투명 바탕 위 검은 원
            cv2.imwrite(str(p), img)
            s = SketchSession()
            s.set_image(p)
            s.run_current()
            h, w = s.result["base"].shape
            for kind in ("original", *stages.PIPELINE_IDS, "edit", "lines"):
                self.assertEqual(s.render(kind).shape[:2], (h, w), kind)

    def test_state_lists_stages_with_values(self):
        st = self.new_session().state()
        ids = [x["id"] for x in st["stages"]]
        self.assertEqual(ids, [x.id for x in stages.ALL_STAGES])
        self.assertIn("edge_mode", st["stages"][2]["params"])
```

`tests/test_agent.py` 상단 import에 아래를 추가한다.

```python
from mirobot_sketch import stages  # noqa: E402
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_agent.SessionTest -v`
Expected: FAIL — `AttributeError: 'SketchSession' object has no attribute 'pipeline'`

- [ ] **Step 3: 컬러 rembg와 `center_px` 구현**

`sketch_pipeline.py`의 `remove_background`를 아래 두 함수로 바꾼다.

```python
def remove_background_bgr(img_path, max_side=DEFAULT_MAX_SIDE, cache_dir=None):
    """rembg로 배경을 제거하고 흰 배경 위에 합성한 컬러(BGR) 이미지를 반환합니다.
    rembg는 선택 기능이라 필요할 때만 import 합니다 (첫 실행 시 모델 다운로드).

    cache_dir를 주면 결과를 원본 파일 내용의 해시 이름으로 저장해 두고 재사용합니다
    (rembg는 이미지 한 장에 약 1분 — GUI를 다시 열 때마다 기다리지 않도록).
    색 차이(Lab) 선 검출도 쓸 수 있게 컬러로 저장합니다 (예전 흑백 캐시 rembg_*.png는 쓰지 않음)."""
    import hashlib
    from pathlib import Path

    with open(img_path, "rb") as f:
        data = f.read()
    cache_file = None
    if cache_dir:
        cache_file = Path(cache_dir) / f"rembg_bgr_{hashlib.sha1(data).hexdigest()[:16]}.png"
        if cache_file.exists():
            cached = cv2.imdecode(np.fromfile(str(cache_file), np.uint8), cv2.IMREAD_COLOR)
            if cached is not None:
                return resize_max_side(cached, max_side)

    from PIL import Image
    try:
        from rembg import remove
    except ImportError as e:
        raise RuntimeError(
            "배경 제거(rembg)가 설치되어 있지 않습니다. "
            "pip install \"mirobot-sketch[rembg]\" 로 설치하거나 배경 제거를 끄세요."
        ) from e

    fg = Image.open(io.BytesIO(remove(data))).convert("RGBA")
    white_bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
    rgb = np.array(Image.alpha_composite(white_bg, fg).convert("RGB"))
    composited = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cv2.imencode(".png", composited)[1].tofile(str(cache_file))
    return resize_max_side(composited, max_side)


def remove_background(img_path, max_side=DEFAULT_MAX_SIDE, cache_dir=None):
    """remove_background_bgr의 흑백판 (명령줄 make_strokes용)."""
    return cv2.cvtColor(remove_background_bgr(img_path, max_side, cache_dir), cv2.COLOR_BGR2GRAY)
```

`paper_mapping.py`의 `placement`에 한 줄을 더한다(좌표 역변환용).

```python
        "center_px": [round(float(center[0]), 3), round(float(center[1]), 3)],
```

- [ ] **Step 4: 세션 구현**

`session.py`에서 `PARAM_KEYS`를 지우고, import에 `import dataclasses`와 `from . import stages`를 더한다. 아래 메서드들을 바꾼다(편집 메서드 `delete_strokes`/`delete_region`/`undo`는 Task 9까지 그대로 둔다).

```python
class SketchSession:
    def __init__(self, cfg=None):
        self.cfg = cfg or de.load_config()
        self.lock = threading.RLock()
        self._run_lock = threading.Lock()   # 파이프라인 계산은 한 번에 하나 (GUI 자동 재계산 + 에이전트)
        self.image_path = None
        self.color = None
        self.image_type = "illustration"
        self.detail = "high"
        self.params = stages.default_params()
        self.apply_preset("illustration")
        self.pipeline = stages.Pipeline()
        self.generation = 0                 # 설정이 바뀔 때마다 +1 (오래된 계산 결과를 버리는 기준)
        self._inputs_cache = {}
        self.result = None
        self.history = []
        self.edit_log = []
        self.sim = None

    # ------------------------------------------------------------ 설정
    def param_specs(self):
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
            self.generation = getattr(self, "generation", 0) + 1

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
```

`state()`에 단계 목록을 넣는다(`s = {...}` 바로 아래).

```python
            s["stages"] = [{"id": st.id, "label": st.label, "params": {p.key: self.params[p.key] for p in st.params}}
                           for st in stages.ALL_STAGES]
```

`render()`를 바꾼다.

```python
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
```

- [ ] **Step 5: GUI 최소 수정 (앱이 계속 동작하도록)**

`gui.py`에서 아래 네 곳을 고친다.

```python
# _push_controls_to_session 안: line_source=... 줄을 다음으로
                edge_mode="dark" if self.line_seg.get().startswith("어두운") else "luma",
# 그리고 s.params.update(...) 다음 줄에 추가
            s.generation += 1
# _sync_controls_from_session 안: line_seg 줄을 다음으로
        self.line_seg.set("어두운 선 중심" if p["edge_mode"] == "dark" else "윤곽 (Canny)")
# _process_worker 안: 캐시 확인과 run을 다음으로
            if s.params.get("rembg") and True not in s._inputs_cache:
            ...
            r = s.run_current()
```

- [ ] **Step 6: 기존 테스트 수정·통과 확인**

`test_update_params_clamps_to_safe_range`는 그대로 통과해야 한다(`box_mm` 상한 120). 전체를 실행한다.

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK, lint 출력 없음

- [ ] **Step 7: 커밋**

```bash
git add mirobot_sketch/session.py mirobot_sketch/sketch_pipeline.py mirobot_sketch/paper_mapping.py mirobot_sketch/gui.py tests/test_agent.py
git commit -m "Session runs the cached stage pipeline; color rembg cache; generation-based stale runs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 에이전트 도구 — 단계 설정과 단계 보기

**Files:**
- Modify: `mirobot_sketch/agent/tools.py`
- Test: `tests/test_agent.py` (`ToolboxTest`)

**Interfaces:**
- Consumes:
  - `stages.PARAM_SPECS`, `stages.PIPELINE_IDS`
  - `SketchSession.run_current()`, `SketchSession.render(kind, ...)`
- Produces:
  - `tools.param_schema() -> dict` (set_params의 properties)
  - `tools.VIEW_KINDS`
  - `SYSTEM_PROMPT` 갱신(단계와 Lab)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
    def test_set_params_schema_comes_from_stage_specs(self):
        props = next(t for t in TOOLS if t["name"] == "set_params")["parameters"]["properties"]
        self.assertEqual(props["edge_mode"]["enum"], ["luma", "lab", "dark"])
        self.assertEqual(props["blur_ksize"]["maximum"], 15)
        for key in stages.PARAM_SPECS:
            self.assertIn(key, props)

    def test_set_params_lab_and_view_each_stage(self):
        tb = AgentToolbox(self.new_session())
        parts, err = tb.call("set_params", {"edge_mode": "lab"})
        self.assertFalse(err, parts)
        self.assertEqual(json.loads(parts[0]["text"])["applied"], {"edge_mode": "lab"})
        for kind in stages.PIPELINE_IDS:
            parts, err = tb.call("view", {"kind": kind})
            self.assertFalse(err, kind)
            self.assertEqual(parts[1]["type"], "image")
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_agent.ToolboxTest -v`
Expected: FAIL — `KeyError: 'edge_mode'`

- [ ] **Step 3: 구현**

`tools.py` import에 `from .. import stages`를 더하고, 아래를 추가·교체한다.

```python
VIEW_KINDS = ["original", *stages.PIPELINE_IDS, "edit", "lines", "strokes", "paper"]


def param_schema():
    """단계 정의(ParamSpec)에서 set_params 입력 스키마를 만듦 (GUI 조절 칸과 같은 출처)."""
    props = {
        "image_type": {"type": "string", "enum": ["photo", "illustration", "manga"],
                       "description": "이미지 종류 프리셋 (먼저 적용된 뒤 나머지 값이 덮어씀)"},
        "detail": {"type": "string", "enum": ["low", "medium", "high"], "description": "상세도 프리셋"},
    }
    for spec in stages.PARAM_SPECS.values():
        if spec.kind == "bool":
            s = {"type": "boolean"}
        elif spec.kind == "choice":
            s = {"type": "string", "enum": [c[0] for c in spec.choices]}
        else:
            s = {"type": "integer" if spec.kind == "int" else "number", "minimum": spec.lo, "maximum": spec.hi}
        s["description"] = f"[{stages.STAGE_BY_ID[_stage_of(spec.key)].label}] {spec.label}. {spec.help}".strip()
        props[spec.key] = s
    return props


def _stage_of(key):
    return next(st.id for st in stages.ALL_STAGES if any(p.key == key for p in st.params))
```

`TOOLS`의 `view`와 `set_params` 항목을 바꾼다.

```python
    {
        "name": "view",
        "description": (
            "그림을 봅니다. kind: original(컬러 원본), 단계별 결과(source 원본 / prep 전처리 / edges 선 검출 / "
            "trace 뼈대·획, 연회색=버린 조각 / dedupe 겹침 제거, 연회색=빠진 조각 / merge 이어 붙이기 / "
            "simplify 단순화), edit(최종 획), paper(A4 종이 미리보기, 펜 굵기 반영), "
            "strokes(획을 종이 mm 좌표로 확대, 10mm 격자, numbered=true면 번호, region_mm=[x0,y0,x1,y1]로 확대)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": VIEW_KINDS},
                "numbered": {"type": "boolean"},
                "region_mm": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_params",
        "description": (
            "처리 설정을 바꾸고, 바뀐 단계부터 다시 계산합니다. 넣은 항목만 바뀌고 범위 밖 값은 잘립니다. "
            "결과로 실제 적용값과 획 수·예상 시간을 돌려줍니다."
        ),
        "parameters": {"type": "object", "properties": param_schema(), "additionalProperties": False},
    },
```

`_set_params`에서 `s.run()`을 `s.run_current()`로 바꾼다.

`SYSTEM_PROMPT`의 "주요 설정" 부분을 아래로 바꾼다.

```text
처리 단계 (view의 kind로 각 단계 결과를 볼 수 있음)
- source 원본: rembg(배경 제거)
- prep 전처리: median_ksize(만화 망점 제거, 11 정도), blur_ksize(가우시안 블러)
- edges 선 검출: edge_mode = luma(밝기) / lab(색 차이 — 밝기가 비슷한 색 경계도 찾음, 컬러 일러스트·사진에 유리) /
  dark(어두운 선 중심선, 선화), canny_low / canny_high
- trace 뼈대·획: min_length_px(작은 덩어리 제거), spur_px(잔가지 제거)
- dedupe 겹침 제거: dedupe_px / merge 이어 붙이기: merge_join_px / simplify 단순화: epsilon_px
- paper 종이: box_mm(그림 긴 변 크기. 실행기 허용 범위를 넘으면 실제 드로잉 전 별도 확인 필요)
- image_type(photo/illustration/manga)과 detail(low/medium/high)은 여러 값을 한꺼번에 채우는 프리셋
- 선이 빠졌으면 어느 단계에서 빠졌는지 view로 단계를 차례로 보고, 그 단계의 값을 바꾸세요.
```

"작업 방식"의 "설정을 다시 처리하면 이전 편집(획 삭제)은 사라집니다" 줄은 그대로 둔다(Task 11에서 바꿈).

- [ ] **Step 4: 통과 확인**

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK (MCP 전체 경로 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add mirobot_sketch/agent/tools.py tests/test_agent.py
git commit -m "Agent tools: set_params schema from stage specs, view any stage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: GUI — 단계 띠, 큰 보기, 자동 조절 칸, 자동 재계산

**Files:**
- Create: `mirobot_sketch/stage_view.py`
- Modify: `mirobot_sketch/gui.py` (레이아웃, 조절 칸, 재계산)
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes:
  - `stages.ALL_STAGES`, `stages.PIPELINE_IDS`
  - `SketchSession.param_specs()`, `update_params()`, `apply_preset()`, `run()`, `dirty_stages()`, `render()`
- Produces:
  - `stage_view.StageStrip(master, stages, on_select, font)`: `.set_thumbnail(id, bgr)`, `.select(id)`, `.set_stale(ids)`
  - `stage_view.BigView(master, font, theme_colors)`:
    - `.show(title, bgr, original_bgr=None, draw_extra=None)`
    - `.redraw()`, `.fit()`, `.view_rect() -> (x0, y0, x1, y1)`
    - `.on_view_change` 콜백과 `.options_frame`(보기 옵션을 넣을 자리)
  - `stage_view.ParamControls(master, specs, values, on_change, font)`: `.set_values(dict)`, `.set_enabled(bool)`
  - `SketchApp`:
    - `.stage_id`
    - `._on_param(key, value)`
    - `._schedule_recompute(delay_ms=RECOMPUTE_DELAY_MS)`
    - `._workers: int` (돌고 있는 재계산 수)

- [ ] **Step 1: 실패하는 스모크 테스트 작성**

```python
# tests/test_gui_smoke.py
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
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_gui_smoke -v`
Expected: FAIL — `AttributeError: 'SketchApp' object has no attribute 'load_image'`

- [ ] **Step 3: `stage_view.py` 구현**

```python
# mirobot_sketch/stage_view.py
"""
단계 띠(썸네일) · 큰 보기(확대·이동·원본 겹치기) · 조절 칸 위젯 (CustomTkinter + matplotlib)
"""

import tkinter as tk

import customtkinter as ctk
import cv2
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image

ACCENT = ("#2563eb", "#3b82f6")
BORDER = ("#dde2ea", "#303644")
TEXT = ("#1f2937", "#e5e7eb")
MUTED = ("#9aa3b2", "#6b7280")
THUMB_H, THUMB_W = 60, 88


class StageStrip(ctk.CTkScrollableFrame):
    """단계 썸네일 띠. 누르면 on_select(stage_id). 다시 계산될 단계는 글자를 흐리게."""

    def __init__(self, master, stages, on_select, font):
        super().__init__(master, orientation="horizontal", height=THUMB_H + 44, fg_color="transparent")
        self.buttons, self._imgs, self.selected = {}, {}, None
        for i, st in enumerate(stages):
            if i:
                ctk.CTkLabel(self, text="→", font=font(12), text_color=MUTED).pack(side="left", padx=1)
            b = ctk.CTkButton(self, text=st.label, compound="top", width=THUMB_W + 12, height=THUMB_H + 34,
                              font=font(11), fg_color="transparent", border_width=2, border_color=BORDER,
                              text_color=TEXT, hover_color=("#e8ecf3", "#2a2f3a"),
                              command=lambda sid=st.id: on_select(sid))
            b.pack(side="left", pady=2)
            self.buttons[st.id] = b

    def set_thumbnail(self, stage_id, img_bgr):
        h, w = img_bgr.shape[:2]
        s = min(THUMB_H / h, THUMB_W / w)
        small = cv2.resize(img_bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        pil = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
        self._imgs[stage_id] = ctk.CTkImage(pil, size=pil.size)
        self.buttons[stage_id].configure(image=self._imgs[stage_id])

    def select(self, stage_id):
        self.selected = stage_id
        for sid, b in self.buttons.items():
            b.configure(border_color=ACCENT if sid == stage_id else BORDER)

    def set_stale(self, stage_ids):
        stale = set(stage_ids)
        for sid, b in self.buttons.items():
            b.configure(text_color=MUTED if sid in stale else TEXT)


class BigView(ctk.CTkFrame):
    """선택한 단계를 크게. 휠=확대, 왼쪽 끌기=이동, 더블클릭=맞춤. 원본 겹치기(투명도)."""

    def __init__(self, master, font, theme_colors):
        super().__init__(master, fg_color="transparent")
        self.theme_colors = theme_colors
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=8, pady=(6, 0))
        self.title = ctk.CTkLabel(bar, text="", font=font(14, "bold"))
        self.title.pack(side="left")
        self.alpha = tk.DoubleVar(value=0.0)
        ctk.CTkSlider(bar, from_=0, to=1, variable=self.alpha, width=110,
                      command=lambda _: self.redraw()).pack(side="right")
        ctk.CTkLabel(bar, text="원본 겹치기", font=font(11)).pack(side="right", padx=4)
        self.options_frame = ctk.CTkFrame(bar, fg_color="transparent")   # 편집 단계 옵션 자리 (Task 12)
        self.options_frame.pack(side="right", padx=8)
        self.fig = Figure(figsize=(8, 6))
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.axis("off")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self.image = self.original = self.draw_extra = None
        self.on_view_change = None
        self._drag = None
        c = self.canvas
        c.mpl_connect("scroll_event", self._on_scroll)
        c.mpl_connect("button_press_event", self._on_press)
        c.mpl_connect("motion_notify_event", self._on_move)
        c.mpl_connect("button_release_event", self._on_release)

    def show(self, title, img_bgr, original_bgr=None, draw_extra=None):
        """같은 크기의 그림이면 확대 위치를 유지."""
        same = self.image is not None and self.image.shape[:2] == img_bgr.shape[:2]
        lim = (self.ax.get_xlim(), self.ax.get_ylim()) if same else None
        self.image, self.original, self.draw_extra = img_bgr, original_bgr, draw_extra
        self.title.configure(text=title)
        self.redraw(lim)

    def redraw(self, lim=None):
        if self.image is None:
            return
        if lim is None and self.ax.images:
            lim = (self.ax.get_xlim(), self.ax.get_ylim())
        bg, _ = self.theme_colors()
        self.fig.set_facecolor(bg)
        self.canvas.get_tk_widget().configure(bg=bg)
        self.ax.clear()
        self.ax.axis("off")
        img = self.image
        a = float(self.alpha.get())
        if self.original is not None and a > 0:
            # 선(어두운 부분)은 그대로, 흰 바탕 자리에 흐린 원본이 비치게
            faded = (self.original.astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8)
            img = np.minimum(img, faded)
        self.ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), interpolation="antialiased")
        if self.draw_extra:
            self.draw_extra(self.ax)
        if lim:
            self.ax.set_xlim(lim[0])
            self.ax.set_ylim(lim[1])
        self.canvas.draw_idle()

    def view_rect(self):
        (x0, x1), (y1, y0) = self.ax.get_xlim(), self.ax.get_ylim()
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def fit(self):
        if self.image is None:
            return
        h, w = self.image.shape[:2]
        self.ax.set_xlim(-0.5, w - 0.5)
        self.ax.set_ylim(h - 0.5, -0.5)
        self._changed()

    def _changed(self):
        if self.on_view_change:
            self.on_view_change()      # 번호 딱지를 보이는 범위에 맞게 다시 그림 (Task 12)
        else:
            self.canvas.draw_idle()

    def _on_scroll(self, e):
        if e.xdata is None:
            return
        f = 0.8 if e.button == "up" else 1.25
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self.ax.set_xlim(e.xdata + (x0 - e.xdata) * f, e.xdata + (x1 - e.xdata) * f)
        self.ax.set_ylim(e.ydata + (y0 - e.ydata) * f, e.ydata + (y1 - e.ydata) * f)
        self._changed()

    def _on_press(self, e):
        if e.dblclick:
            self.fit()
        elif e.button == 1 and e.inaxes is self.ax:
            self._drag = (e.x, e.y, self.ax.get_xlim(), self.ax.get_ylim())

    def _on_move(self, e):
        if not self._drag or e.x is None:
            return
        x, y, xl, yl = self._drag
        box = self.ax.get_window_extent()
        dx = (e.x - x) * (xl[1] - xl[0]) / box.width
        dy = (e.y - y) * (yl[1] - yl[0]) / box.height
        self.ax.set_xlim(xl[0] - dx, xl[1] - dx)
        self.ax.set_ylim(yl[0] - dy, yl[1] - dy)
        self.canvas.draw_idle()

    def _on_release(self, e):
        if self._drag:
            self._drag = None
            self._changed()


class ParamControls(ctk.CTkFrame):
    """ParamSpec 목록으로 조절 칸을 만듦. 값이 바뀌면 on_change(key, value)."""

    def __init__(self, master, specs, values, on_change, font):
        super().__init__(master, fg_color="transparent")
        self.specs, self.on_change, self._muted = {s.key: s for s in specs}, on_change, False
        self.vars, self.widgets = {}, []
        for s in specs:
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=(6, 0))
            if s.kind == "bool":
                var = tk.BooleanVar(value=bool(values[s.key]))
                w = ctk.CTkSwitch(row, text=s.label, variable=var, font=font(12),
                                  command=lambda k=s.key, v=var: self._emit(k, v.get()))
                w.pack(anchor="w")
            elif s.kind == "choice":
                ctk.CTkLabel(row, text=s.label, font=font(12), anchor="w").pack(fill="x")
                names = [c[1] for c in s.choices]
                var = tk.StringVar(value=dict(s.choices)[values[s.key]])
                w = ctk.CTkSegmentedButton(self, values=names, variable=var, font=font(12),
                                           command=lambda name, sp=s: self._emit(
                                               sp.key, next(c[0] for c in sp.choices if c[1] == name)))
                w.pack(fill="x", padx=14, pady=(2, 0))
            else:
                ctk.CTkLabel(row, text=s.label, font=font(12), anchor="w").pack(side="left")
                var = tk.StringVar(value=self._fmt(s, values[s.key]))
                entry = ctk.CTkEntry(row, textvariable=var, width=58, font=font(12), justify="right")
                entry.pack(side="right")
                entry.bind("<Return>", lambda _e, sp=s, v=var: self._from_entry(sp, v))
                entry.bind("<FocusOut>", lambda _e, sp=s, v=var: self._from_entry(sp, v))
                steps = max(1, int(round((s.hi - s.lo) / (s.step or 1))))
                w = ctk.CTkSlider(self, from_=s.lo, to=s.hi, number_of_steps=steps,
                                  button_color=ACCENT, progress_color=ACCENT,
                                  command=lambda val, sp=s, v=var: self._from_slider(sp, v, val))
                w.set(values[s.key])
                w.pack(fill="x", padx=10, pady=(2, 0))
                self.widgets.append(entry)
                self.vars[s.key + ":slider"] = w
            if s.help:
                ctk.CTkLabel(self, text=s.help, font=font(10), text_color=MUTED, anchor="w", justify="left",
                             wraplength=290).pack(fill="x", padx=14)
            self.vars[s.key] = var
            self.widgets.append(w)

    @staticmethod
    def _fmt(spec, v):
        return f"{v:.1f}" if spec.kind == "float" else str(int(v))

    def _emit(self, key, value):
        if not self._muted:
            self.on_change(key, value)

    def _from_slider(self, spec, var, val):
        v = spec.clamp(val)
        var.set(self._fmt(spec, v))
        self._emit(spec.key, v)

    def _from_entry(self, spec, var):
        try:
            v = spec.clamp(float(var.get()))
        except ValueError:
            return
        var.set(self._fmt(spec, v))
        self.vars[spec.key + ":slider"].set(v)
        self._emit(spec.key, v)

    def set_values(self, values):
        """에이전트·프리셋이 바꾼 값을 화면에 반영 (on_change는 부르지 않음)."""
        self._muted = True
        try:
            for key, s in self.specs.items():
                v = values[key]
                if s.kind == "bool":
                    self.vars[key].set(bool(v))
                elif s.kind == "choice":
                    self.vars[key].set(dict(s.choices)[v])
                else:
                    self.vars[key].set(self._fmt(s, v))
                    self.vars[key + ":slider"].set(v)
        finally:
            self._muted = False

    def set_enabled(self, enabled):
        for w in self.widgets:
            w.configure(state="normal" if enabled else "disabled")
```

- [ ] **Step 4: `gui.py` 개편**

바꿀 곳은 다음과 같다.
- **import:** `from . import stages`, `from .stage_view import BigView, ParamControls, StageStrip`를 더한다.
- **상수:** `RECOMPUTE_DELAY_MS = 300`을 더한다.
- **지울 것:**
  - `_build_ui`의 "② 상세도와 크기"의 `box_mm` 슬라이더와 "세부 조절" 카드 `c4` 전체
  - matplotlib 4칸(`self.fig`, `ax_*`)
  - `_slider`, `_style_figure`, `_placeholder`, `_show_original`, `_draw_preview`
  - `_push_controls_to_session`
- **`__init__`:** `self._build_ui()` 전에 `self.stage_id = "source"`, `self._workers = 0`, `self._recompute_after = None`을 넣는다.

`_build_ui`의 왼쪽 패널은 ①(이미지 열기, 종류) 카드를 그대로 두고, 그 아래를 다음으로 바꾼다.

```python
        c2 = Card(side, "② 상세도")
        c2.pack(fill="x", pady=(0, 10))
        self.detail_seg = ctk.CTkSegmentedButton(c2, values=DETAIL_LABELS, command=lambda _: self.apply_detail_preset(),
                                                 font=font(12))
        self.detail_seg.set("높음")
        self.detail_seg.pack(fill="x", padx=14, pady=(2, 12))

        self.ctrl_card = Card(side)
        self.ctrl_card.pack(fill="x", pady=(0, 10))
        self.ctrl_title = ctk.CTkLabel(self.ctrl_card, text="", font=font(14, "bold"), anchor="w")
        self.ctrl_title.pack(fill="x", padx=14, pady=(12, 0))
        self.controls = None

        c3 = Card(side, "③ 실행")
        c3.pack(fill="x", pady=(0, 10))
        self.run_btn = ctk.CTkButton(c3, text="지금 다시 계산", command=lambda: self._schedule_recompute(0),
                                     font=font(13), height=36, fg_color=ACCENT)
        self.run_btn.pack(fill="x", padx=14, pady=(2, 6))
        # (sim_btn, 내보내기/RViz 줄, progress, status는 기존 코드 그대로)
```

오른쪽은 다음으로 바꾼다.

```python
        right = ctk.CTkFrame(self.root, fg_color="transparent")
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 18), pady=(0, 18))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        self.strip = StageStrip(right, stages.ALL_STAGES, self.select_stage, font)
        self.strip.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        view_card = Card(right)
        view_card.grid(row=1, column=0, sticky="nsew")
        self.view = BigView(view_card, font, self._theme_colors)
        self.view.pack(fill="both", expand=True)
        stats = ctk.CTkFrame(right, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        # (StatCard 4개는 기존 코드 그대로)
        self._build_controls()
        self.strip.select(self.stage_id)
```

`set_mode`를 다음으로 바꾼다.

```python
    def set_mode(self, value):
        ctk.set_appearance_mode("Light" if value == "라이트" else "Dark")
        self.view.redraw()
```

프리셋과 조절 칸:

```python
    def _build_controls(self):
        if self.controls is not None:
            self.controls.destroy()
        st = stages.STAGE_BY_ID[self.stage_id]
        specs = [self.session.param_specs()[p.key] for p in st.params]
        self.ctrl_title.configure(text=f"조절: {st.label}" + ("" if specs else " (조절 항목 없음)"))
        self.controls = ParamControls(self.ctrl_card, specs, self.session.params, self._on_param, font)
        self.controls.pack(fill="x", pady=(0, 12))
        self.controls.set_enabled(not self._agent_busy)

    def apply_type_preset(self):
        t = presets.IMAGE_TYPES[self._type_key()]
        self.type_hint.configure(text=t["why"])
        self.session.apply_preset(self._type_key())
        self._sync_controls_from_session()
        self._schedule_recompute()

    def apply_detail_preset(self):
        self.session.apply_preset(detail=self._detail_key())
        self._sync_controls_from_session()
        self._schedule_recompute()

    def _sync_controls_from_session(self):
        s = self.session
        self.type_seg.set(presets.IMAGE_TYPES[s.image_type]["label"])
        self.type_hint.configure(text=presets.IMAGE_TYPES[s.image_type]["why"])
        self.detail_seg.set(DETAIL_LABELS[DETAIL_KEYS.index(s.detail)])
        if self.controls is not None:
            self.controls.set_values(s.params)

    def _on_param(self, key, value):
        if self._agent_busy:
            return
        self.session.update_params({key: value})
        self._schedule_recompute()
```

이미지 열기, 단계 선택, 재계산:

```python
    def open_image(self):
        path = filedialog.askopenfilename(
            initialdir=str(paths.input_dir()),
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.jfif *.bmp *.webp")])
        if path:
            self.load_image(path)

    def load_image(self, path):
        try:
            self.session.set_image(path)
        except ValueError as e:
            messagebox.showerror("오류", str(e))
            return
        self.traj_btn.configure(state="disabled")
        self.path_label.configure(text=Path(path).name)
        self.strip.set_thumbnail("source", self.session.color)
        self.select_stage("source")
        self._schedule_recompute(0)

    def select_stage(self, stage_id):
        self.stage_id = stage_id
        self.strip.select(stage_id)
        self._build_controls()
        self._show_stage()

    def _show_stage(self):
        s = self.session
        st = stages.STAGE_BY_ID[self.stage_id]
        if s.result is None:
            if s.color is not None:
                self.view.show(f"{st.label} (계산 전)", s.color)
            return
        overlay = None if self.stage_id in ("source", "paper") else s.color
        self.view.show(st.label, s.render(self.stage_id), overlay)

    def _schedule_recompute(self, delay_ms=RECOMPUTE_DELAY_MS):
        if self.img_path is None:
            return
        if self._recompute_after is not None:
            self.root.after_cancel(self._recompute_after)
        self._recompute_after = self.root.after(delay_ms, self._start_recompute)

    def _start_recompute(self):
        self._recompute_after = None
        if self._agent_busy or self.img_path is None:
            return
        self.strip.set_stale(self.session.dirty_stages())
        if self._workers == 0:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        self._workers += 1
        if self.session.params.get("rembg") and True not in self.session._inputs_cache:
            self._set_status("배경 제거 중 (rembg, 한 번만 오래 걸림)...")
        else:
            self._set_status("계산 중...")
        threading.Thread(target=self._recompute_worker, daemon=True).start()

    def _recompute_worker(self):
        try:
            r = self.session.run()          # None이면 더 새로운 설정의 계산이 뒤따름
            if r is not None:
                self._ui(self._show_result, r)
        except Exception as e:  # SessionError 포함: 화면에 보여 줌
            self._set_status(f"오류: {e}")
        finally:
            self._ui(self._worker_done)

    def _worker_done(self):
        self._workers -= 1
        if self._workers == 0:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self.strip.set_stale(())
```

`_show_result`의 `self._draw_preview(r)` 줄을 다음으로 바꾼다.

```python
        for st in stages.ALL_STAGES:
            self.strip.set_thumbnail(st.id, self.session.render(st.id))
        self._show_stage()
```

그 밖의 정리:
- `process`와 `_process_worker` 메서드를 지운다(다시 계산 버튼과 자동 재계산이 대신한다).
- `_start_busy`, `_end_busy`는 시뮬레이션과 RViz가 계속 쓴다.

`_refresh_from_session`과 `agent_busy`를 바꾼다.

```python
    def _refresh_from_session(self, what="result"):
        self._sync_controls_from_session()
        if self.session.result is not None:
            self._show_result(self.session.result, status="에이전트가 결과를 바꿨습니다.")
        if self.session.sim:
            self._show_sim(self.session.sim["summary"])

    def agent_busy(self, busy):
        """에이전트가 작업 중이면 조절 칸·버튼을 잠금 (같은 세션을 동시에 바꾸지 않게)."""
        self._agent_busy = busy
        state = "disabled" if busy or self.busy else "normal"
        self.run_btn.configure(state=state)
        self.sim_btn.configure(state=state)
        if self.controls is not None:
            self.controls.set_enabled(not busy)
```

`apply_type_preset()`은 `__init__`에서 `_build_ui` 뒤에 불린다. 이 시점에는 이미지가 없으므로 `_schedule_recompute`가 바로 반환된다.

- [ ] **Step 5: 통과 확인**

Run: `cd tests && python -m unittest test_gui_smoke -v`
Expected: PASS (화면이 없는 환경이면 skipped)

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK

- [ ] **Step 6: 직접 보고 확인 (라이트/다크)**

스크래치 스크립트로 앱을 띄워 `input/illust1_color.jpg`를 연다. `edges` 단계를 고르고 원본 겹치기를 0.5로 올린 뒤 `app.view.fig.savefig(...)`로 저장해 이미지를 직접 본다. 다크 모드도 같게 확인한다. 확인할 것:
- 단계 띠에 썸네일 9개가 보이는지
- 휠 확대 후 값을 바꿔도 확대 위치가 유지되는지
- 슬라이더를 놓고 0.3초 뒤 결과가 바뀌는지

- [ ] **Step 7: 커밋**

```bash
git add mirobot_sketch/stage_view.py mirobot_sketch/gui.py tests/test_gui_smoke.py
git commit -m "GUI: stage strip, zoomable big view with original overlay, auto-generated controls, debounced recompute

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 1b — 편집 제안

### Task 8: `edits.py` — 점 편집 함수와 모양 기반 재적용

**Files:**
- Create: `mirobot_sketch/edits.py`
- Test: `tests/test_edits.py`

**Interfaces:**
- Produces (모두 px 좌표, 새 배열 반환, 입력은 바꾸지 않음):
  - `EditError(ValueError)`
  - 상수: `MAX_OPS = 200`, `MATCH_TOL_PX = 2`, `MATCH_FRACTION = 0.6`, `GREEN`, `RED`
  - `as_poly(p) -> (N,2) float64` (점 2개 미만이면 `EditError`)
  - `densify(p, step=1.0) -> (M,2) float64`
  - 점 편집:
    - `move_point(p, i, xy)`
    - `delete_points(p, indices)`
    - `insert_point(p, after, xy)`
    - `smooth(p, strength)` (strength 1~5)
    - `split(p, i) -> (a, b)`
    - `join(a, b) -> poly`
  - `remove_matching(strokes, removed_polys, shape) -> (keep_indices, hit_flags)`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_edits.py
"""획 편집 함수와 모양 기반 재적용."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import edits  # noqa: E402

LINE = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], float)


class PointOpsTest(unittest.TestCase):
    def test_move_delete_insert(self):
        m = edits.move_point(LINE, 1, (10, 5))
        self.assertEqual(m[1].tolist(), [10, 5])
        self.assertEqual(LINE[1].tolist(), [10, 0])            # 원본은 그대로
        self.assertEqual(len(edits.delete_points(LINE, [1, 2])), 2)
        self.assertEqual(edits.insert_point(LINE, 0, (5, 1))[1].tolist(), [5, 1])
        with self.assertRaises(edits.EditError):
            edits.delete_points(LINE, [0, 1, 2])               # 2개 미만이 남음
        with self.assertRaises(edits.EditError):
            edits.move_point(LINE, 9, (0, 0))

    def test_smooth_keeps_endpoints_and_reduces_zigzag(self):
        zig = np.array([[x, 3 * (x % 2)] for x in range(0, 40)], float)
        sm = edits.smooth(zig, 3)
        self.assertEqual(sm[0].tolist(), zig[0].tolist())
        self.assertEqual(sm[-1].tolist(), zig[-1].tolist())
        self.assertLess(np.abs(np.diff(edits.densify(sm)[:, 1])).max(), 1.5)
        with self.assertRaises(edits.EditError):
            edits.smooth(zig, 9)

    def test_split_and_join_roundtrip(self):
        a, b = edits.split(LINE, 2)
        self.assertEqual(a[-1].tolist(), b[0].tolist())
        j = edits.join(b[::-1], a)                            # 방향이 달라도 가까운 끝끼리
        self.assertAlmostEqual(float(np.hypot(*np.diff(j, axis=0).T).sum()), 30.0)   # 원래 길이 그대로
        with self.assertRaises(edits.EditError):
            edits.split(LINE, 0)


class RemoveMatchingTest(unittest.TestCase):
    def test_removed_shape_matches_nearby_recomputed_stroke(self):
        old = np.array([[10, 10], [90, 10]], float)
        new_same = np.array([[11, 11], [89, 11]], float)       # 다시 계산해 1px 어긋난 같은 선
        other = np.array([[10, 50], [90, 50]], float)
        keep, hit = edits.remove_matching([new_same, other], [old, np.array([[0, 90], [5, 95]], float)],
                                          (100, 100))
        self.assertEqual(keep, [1])
        self.assertEqual(hit, [True, False])                    # 두 번째 지운 모양은 대상 없음 -> 미적용

    def test_no_removed_keeps_all(self):
        self.assertEqual(edits.remove_matching([LINE], [], (10, 40)), ([0], []))
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_edits -v`
Expected: FAIL — `ImportError: cannot import name 'edits'`

- [ ] **Step 3: 구현**

```python
# mirobot_sketch/edits.py
"""
획 편집 — 점 편집 함수, 모양 기반 재적용, 초록/빨강 제안 그림
==============================================================
모든 좌표는 처리 이미지의 px(float). 함수는 새 배열을 돌려주고 입력은 바꾸지 않습니다.
편집은 "번호"가 아니라 "모양"으로 기록됩니다: 설정을 바꿔 다시 계산하면 번호는 바뀌지만,
지운 모양과 겹치는 새 획을 다시 지우고(remove_matching) 추가한 모양은 그대로 더합니다.
"""

import cv2
import numpy as np

MAX_OPS = 200            # 한 번에 받는 편집 수
MATCH_TOL_PX = 2         # 지운 모양과 이만큼 가까우면 같은 선
MATCH_FRACTION = 0.6     # 획 점의 이 비율 이상이 지운 모양 위면 다시 지움
GREEN = (40, 160, 40)    # BGR: 새로 생길 모양
RED = (40, 40, 220)      # BGR: 사라질 모양
INK = (70, 70, 70)
CANDIDATE = (175, 175, 175)


class EditError(ValueError):
    """사용자·에이전트에게 보여 줄 편집 오류."""


def as_poly(p):
    a = np.asarray(p, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] != 2 or len(a) < 2:
        raise EditError("선은 (x, y) 점 2개 이상이어야 합니다")
    return a


def _check_index(p, i):
    if not 0 <= int(i) < len(p):
        raise EditError(f"점 번호 {i}가 범위 밖입니다 (0~{len(p) - 1})")
    return int(i)


def densify(p, step=1.0):
    """점 사이를 step 간격으로 채움."""
    p = as_poly(p)
    out = [p[0]]
    for a, b in zip(p[:-1], p[1:]):
        n = max(1, int(np.ceil(np.hypot(*(b - a)) / step)))
        out.extend(a + (b - a) * (k / n) for k in range(1, n + 1))
    return np.array(out)


def move_point(p, i, xy):
    p = as_poly(p).copy()
    p[_check_index(p, i)] = xy
    return p


def delete_points(p, indices):
    p = as_poly(p)
    drop = {_check_index(p, i) for i in indices}
    keep = [k for k in range(len(p)) if k not in drop]
    if len(keep) < 2:
        raise EditError("점을 지운 뒤 2개 이상 남아야 합니다")
    return p[keep]


def insert_point(p, after, xy):
    p = as_poly(p)
    return np.insert(p, _check_index(p, after) + 1, xy, axis=0)


def smooth(p, strength=2):
    """이동 평균(1-2-1)으로 매끄럽게. 끝점 고정, 닫힌 획은 고리째. strength 1~5."""
    strength = int(strength)
    if not 1 <= strength <= 5:
        raise EditError("strength는 1~5")
    d = densify(p)
    if len(d) < 5:
        return as_poly(p).copy()
    closed = np.allclose(d[0], d[-1])
    for _ in range(strength * 4):
        if closed:
            body = d[:-1]
            body = (np.roll(body, 1, 0) + 2 * body + np.roll(body, -1, 0)) / 4
            d = np.vstack([body, body[:1]])
        else:
            m = d.copy()
            m[1:-1] = (d[:-2] + 2 * d[1:-1] + d[2:]) / 4
            d = m
    approx = cv2.approxPolyDP(d.astype(np.float32).reshape(-1, 1, 2), 0.5, closed=False).reshape(-1, 2)
    out = approx.astype(np.float64) if len(approx) >= 2 else d[[0, -1]]
    out[0], out[-1] = d[0], d[-1]
    return out


def split(p, i):
    p = as_poly(p)
    i = int(i)
    if not 0 < i < len(p) - 1:
        raise EditError(f"자를 점 번호는 1~{len(p) - 2}")
    return p[:i + 1].copy(), p[i:].copy()


def join(a, b):
    """가까운 끝끼리 이어 한 획으로."""
    a, b = as_poly(a), as_poly(b)
    options = [(np.hypot(*(a[-1] - b[0])), a, b), (np.hypot(*(a[-1] - b[-1])), a, b[::-1]),
               (np.hypot(*(a[0] - b[-1])), b, a), (np.hypot(*(a[0] - b[0])), a[::-1], b)]
    _, x, y = min(options, key=lambda t: t[0])
    return np.vstack([x, y])


def remove_matching(strokes, removed, shape):
    """지운 모양과 겹치는 획을 뺌. 반환: (남길 획 인덱스, 지운 모양마다 무언가를 지웠는지)."""
    if not removed:
        return list(range(len(strokes))), []
    h, w = shape[:2]
    label = np.zeros((h, w), np.uint16)
    for k, r in enumerate(removed):
        cv2.polylines(label, [np.round(as_poly(r)).astype(np.int32).reshape(-1, 1, 2)], False, k + 1,
                      2 * MATCH_TOL_PX + 1)
    hit, keep = [False] * len(removed), []
    for i, s in enumerate(strokes):
        d = np.round(densify(s)).astype(int)
        lab = label[np.clip(d[:, 1], 0, h - 1), np.clip(d[:, 0], 0, w - 1)]
        if (lab > 0).mean() >= MATCH_FRACTION:
            for k in np.unique(lab[lab > 0]):
                hit[int(k) - 1] = True
        else:
            keep.append(i)
    return keep, hit
```

- [ ] **Step 4: 통과 확인**

Run: `cd tests && python -m unittest test_edits -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add mirobot_sketch/edits.py tests/test_edits.py
git commit -m "Add stroke point-edit functions and shape-based edit replay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 세션 — 번호표, 후보, 제안·적용·되돌리기

**Files:**
- Modify: `mirobot_sketch/session.py` (편집 부분 전체 교체, `run()`과 `state()` 확장)
- Test: `tests/test_agent.py` (`SessionTest`의 편집 테스트 교체 + 새 `EditSessionTest`)

**Interfaces:**
- Consumes:
  - `edits.*`, `stages.candidates_of`
  - `pm.pixels_to_paper`(placement의 `center_px`)
- Produces:
  - 상태 필드:
    - `SketchSession.table: {id: {"kind": "stroke"|"candidate"|"gone", "poly": ndarray px, "reason": str}}`
    - `SketchSession.proposals: {id: {"id", "group"}}`
    - `SketchSession.book = {"removed": [{"poly", "reason": "deleted"|"replaced"}], "added": [poly]}`
  - 편집 메서드:
    - `propose_edits(ops, apply_now=False) -> {"proposed": [ids], "total": n}`. `apply_now`면 `apply_proposals` 결과를 돌려준다.
    - `apply_proposals(exclude=None, only=None) -> {"applied": [ids], "not_applied": [ids], "note": str}`
    - `discard_proposals(ids=None) -> int`
    - `undo() -> str | None`
  - 조회와 좌표 도우미:
    - `list_strokes(region_mm=None, include_candidates=False, limit=300) -> {"rows": [...], "truncated": bool}`
    - `get_stroke(id) -> {"id", "kind", "reason", "points_mm": [[i, x, y]...], "truncated": bool}`
    - `proposal_views() -> [{"id", "before": poly|None, "after": poly|None}]`
    - `proposal_region_mm(ids=None) -> [x0, y0, x1, y1] | None`
    - `mm_to_px(xy)`, `px_to_mm(points)`
  - `state()["edit"] = {"proposals": [...], "candidates": n, "unapplied_edits": n, "notice": str}`
  - 지우는 메서드: `delete_strokes`, `delete_region` (`propose_edits`의 `delete`, `delete_region`으로 대체)

- [ ] **Step 1: 기존 편집 테스트 교체와 새 테스트 작성**

`SessionTest`에서 `test_delete_and_undo`, `test_delete_region_outside_keeps_only_region`, `test_rerun_clears_edits`, 그리고 `test_invalid_inputs_raise_session_error`의 `delete_strokes` 줄을 지운다. 아래 클래스를 추가한다.

```python
class EditSessionTest(SessionTestBase):
    def strokes(self, s):
        return sorted(i for i, e in s.table.items() if e["kind"] == "stroke")

    def test_delete_is_proposed_then_applied_and_undone(self):
        s = self.new_session()
        ids = self.strokes(s)
        r = s.propose_edits([{"op": "delete", "ids": [ids[0]]}])
        self.assertEqual(r["proposed"], [ids[0]])
        self.assertEqual(self.strokes(s), ids)                    # 제안만으로는 안 바뀜
        s.apply_proposals()
        self.assertEqual(self.strokes(s), ids[1:])
        self.assertEqual(s.table[ids[0]]["reason"], "deleted")    # 같은 번호의 후보가 됨
        self.assertIsNotNone(s.undo())
        self.assertEqual(self.strokes(s), ids)

    def test_restore_candidate_and_exclude(self):
        s = self.new_session()
        cands = sorted(i for i, e in s.table.items() if e["kind"] == "candidate")
        self.assertTrue(cands, "합성 이미지의 잡음 점이 후보로 남아야 함")
        first = self.strokes(s)[0]
        s.propose_edits([{"op": "restore", "ids": [cands[0]]}, {"op": "delete", "ids": [first]}])
        out = s.apply_proposals(exclude=[first])
        self.assertEqual(out["applied"], [cands[0]])
        self.assertEqual(s.table[cands[0]]["kind"], "stroke")
        self.assertEqual(s.table[first]["kind"], "stroke")
        self.assertEqual(s.proposals, {})                          # 적용하면 제안 목록은 비워짐

    def test_point_edit_in_mm_and_bounds(self):
        s = self.new_session()
        sid = self.strokes(s)[0]
        pts = s.get_stroke(sid)["points_mm"]
        target = [pts[0][1] * 0.9, pts[0][2] * 0.9]
        expected_px = s.mm_to_px(target)          # 적용 후엔 테두리 상자가 바뀌어 mm 배치가 달라질 수 있어 px로 비교
        s.propose_edits([{"op": "move_point", "id": sid, "index": 0, "to_mm": target}], apply_now=True)
        self.assertTrue(np.allclose(s.table[sid]["poly"][0], expected_px))
        with self.assertRaises(SessionError):
            s.propose_edits([{"op": "move_point", "id": sid, "index": 0, "to_mm": [80, 0]}])   # 60mm 밖

    def test_invalid_batch_changes_nothing(self):
        s = self.new_session()
        before = {i: e["kind"] for i, e in s.table.items()}
        sid = self.strokes(s)[0]
        cand = next(i for i, e in s.table.items() if e["kind"] == "candidate")
        for bad in ([{"op": "delete", "ids": [sid]}, {"op": "delete", "ids": [10 ** 6]}],
                    [{"op": "delete", "ids": [cand]}],
                    [{"op": "delete_points", "id": sid, "indices": [999]}],
                    [{"op": "teleport"}],
                    [{"op": "delete", "ids": [sid]}] * (edits.MAX_OPS + 1)):
            with self.assertRaises(SessionError):
                s.propose_edits(bad)
        self.assertEqual({i: e["kind"] for i, e in s.table.items()}, before)
        self.assertEqual(s.proposals, {})

    def test_cannot_delete_every_stroke(self):
        s = self.new_session()
        s.propose_edits([{"op": "delete", "ids": self.strokes(s)}])
        with self.assertRaises(SessionError):
            s.apply_proposals()

    def test_edits_survive_recompute_and_pending_proposals_are_cancelled(self):
        s = self.new_session()
        ids = self.strokes(s)
        victim = s.table[ids[0]]["poly"].copy()
        s.propose_edits([{"op": "delete", "ids": [ids[0]]}], apply_now=True)
        s.propose_edits([{"op": "delete", "ids": [ids[1]]}])           # 적용 안 한 제안
        s.update_params({"canny_low": s.params["canny_low"] + 5})
        s.run_current()
        self.assertEqual(s.proposals, {})
        self.assertIn("취소", s.state()["edit"]["notice"])
        polys = [e["poly"] for e in s.table.values() if e["kind"] == "stroke"]
        close = [p for p in polys if edits.remove_matching([p], [victim], s.result["base"].shape)[0] == []]
        self.assertEqual(close, [])                                      # 지운 선은 다시 지워짐

    def test_box_change_keeps_numbers_and_proposals(self):
        s = self.new_session()
        sid = self.strokes(s)[0]
        s.propose_edits([{"op": "delete", "ids": [sid]}])
        s.update_params({"box_mm": 80})
        s.run_current()
        self.assertIn(sid, s.proposals)

    def test_split_join_group_all_or_nothing(self):
        s = self.new_session()
        a, b = self.strokes(s)[:2]
        s.propose_edits([{"op": "join", "a": a, "b": b}])
        out = s.apply_proposals(exclude=[b])
        self.assertEqual(out["applied"], [])
        self.assertIn("묶", out["note"])

    def test_list_strokes_is_truncated(self):
        s = self.new_session()
        r = s.list_strokes(include_candidates=True, limit=2)
        self.assertEqual(len(r["rows"]), 2)
        self.assertTrue(r["truncated"])
        self.assertEqual(set(r["rows"][0]), {"id", "kind", "reason", "length_mm", "bbox_mm", "points"})
```

`tests/test_agent.py` 상단 import에 아래를 추가한다.

```python
from mirobot_sketch import edits  # noqa: E402
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_agent.EditSessionTest -v`
Expected: FAIL — `AttributeError: 'SketchSession' object has no attribute 'table'`

- [ ] **Step 3: 세션 구현**

import에 `from . import edits`를 추가한다. `__init__`의 편집 필드를 아래로 바꾼다(`self.history`, `self.edit_log`는 유지한다).

```python
        self.table = {}          # 번호 -> {"kind": stroke|candidate|gone, "poly": px 배열, "reason": 이유}
        self.next_id = 1
        self.book = {"removed": [], "added": []}   # 모양 기반 편집 기록 (다시 계산해도 유지)
        self.pending = None      # 제안이 반영된 번호표 사본 (제안이 없으면 None)
        self.proposals = {}      # 번호 -> {"id", "group"}
        self._groups, self._group_seq = {}, 0
        self.unapplied = 0
        self.notice = ""
        self._last_simplify = None
```

`set_image`에서 `self.history, self.edit_log = [], []` 다음 줄에 아래를 넣는다.

```python
            self.book = {"removed": [], "added": []}
            self._clear_proposals()
            self._last_simplify = None
```

`run()`의 결과 조립 부분(`strokes_px = ...`부터 `return self.result`까지)을 다음으로 바꾼다.

```python
            with self.lock:
                if self.generation != gen:
                    return None
                same = outs["simplify"] is self._last_simplify and self.result is not None
                self.result = {"base": inputs["gray"], "color": self.color, "edges": outs["edges"]["edges"],
                               "stages": outs, "path": self.image_path, "params": p,
                               "image_type": self.image_type, "detail": self.detail,
                               "placement": self.result["placement"] if same else None}
                if not same:   # 파이프라인 결과가 바뀜: 번호를 새로 매기고, 적용 전 제안은 취소
                    n = len(self.proposals)
                    self._build_table(outs, inputs["gray"].shape)
                    self._clear_proposals()
                    self.history = []
                    self.notice = "설정이 바뀌어 번호를 새로 매겼습니다" + (f" (제안 {n}건을 취소했습니다)" if n else "")
                    self._last_simplify = outs["simplify"]
                self._refresh_drawing()
                return self.result
```

`self.history, self.edit_log, self.sim = [], [], None` 줄은 지운다. `edit_log`는 적용된 편집 설명으로 유지되고, `history`는 번호표 스냅숏이라 번호가 바뀌면 비운다(위 코드).

편집 부분(`_push`, `delete_strokes`, `delete_region`, `undo`)을 지우고 아래로 바꾼다.

```python
    # ------------------------------------------------------------ 번호표
    def _build_table(self, outs, shape):
        """파이프라인 결과 + 편집 기록 -> 번호표 (획 1..N, 추가한 획, 후보 순)."""
        base = outs["simplify"]["strokes"]
        keep, hit = edits.remove_matching(base, [r["poly"] for r in self.book["removed"]], shape)
        table, nid = {}, 1

        def put(kind, poly, reason):
            nonlocal nid
            table[nid] = {"kind": kind, "poly": poly, "reason": reason}
            nid += 1

        for i in keep:
            put("stroke", np.asarray(base[i], np.float64), "")
        for a in self.book["added"]:
            put("stroke", a, "added")
        for poly, reason in stages.candidates_of(outs):
            put("candidate", np.asarray(sp.simplify_strokes([poly], 1.0)[0], np.float64), reason)
        for r, h in zip(self.book["removed"], hit):
            if h and r["reason"] == "deleted":
                put("candidate", r["poly"], "deleted")
        self.table, self.next_id = table, nid
        self.unapplied = hit.count(False)

    def _refresh_drawing(self):
        """번호표의 획 -> 그리는 순서 -> 종이 mm -> 시간·미리보기."""
        strokes = [e["poly"] for _, e in sorted(self.table.items()) if e["kind"] == "stroke"]
        if not strokes:
            raise SessionError("획이 없습니다. 상세도를 높이거나 Canny 하한을 낮춰 보세요.")
        ordered = sp.order_strokes(strokes)
        box = self.params["box_mm"]
        strokes_mm, placement = pm.pixels_to_paper(ordered, box_mm=(box, box))
        self.result["placement"] = placement
        self._set_strokes(list(ordered), list(strokes_mm))

    # ------------------------------------------------------------ 좌표
    def mm_to_px(self, xy):
        x, y = (float(v) for v in xy)
        lim = self.cfg["limits_pending_verification"]
        if abs(x) > lim["max_abs_paper_x_mm"] or abs(y) > lim["max_abs_paper_y_mm"]:
            raise SessionError(f"좌표 ({x:.1f}, {y:.1f})mm가 허용 범위 ±{lim['max_abs_paper_x_mm']:.0f}mm 밖입니다")
        pl = self.result["placement"]
        s, (cx, cy) = pl["scale_mm_per_px"], pl["center_px"]
        return (x / s + cx, -y / s + cy)

    def px_to_mm(self, pts):
        pl = self.result["placement"]
        s, (cx, cy) = pl["scale_mm_per_px"], pl["center_px"]
        p = np.asarray(pts, np.float64)
        return np.column_stack([(p[:, 0] - cx) * s, -(p[:, 1] - cy) * s])

    def _region_px(self, region_mm):
        x0, y0, x1, y1 = [float(v) for v in region_mm]
        pl = self.result["placement"]
        s, (cx, cy) = pl["scale_mm_per_px"], pl["center_px"]
        xs, ys = sorted((x0 / s + cx, x1 / s + cx)), sorted((-y0 / s + cy, -y1 / s + cy))
        return xs[0], ys[0], xs[1], ys[1]

    # ------------------------------------------------------------ 편집 실행 (번호표 사본에)
    def _exec(self, op, table, alloc):
        """편집 하나를 table(사본)에 반영. 반환: 묶음 목록 [[번호...], ...]."""
        if not isinstance(op, dict):
            raise SessionError("편집은 {\"op\": ...} 객체여야 합니다")
        name = op.get("op")

        def entry(i, kind="stroke"):
            e = table.get(int(i))
            if e is None or e["kind"] != kind:
                what = "획" if kind == "stroke" else "후보"
                raise SessionError(f"{i}번은 {what}가 아닙니다")
            return int(i), e

        if name in ("delete", "delete_region"):
            ids = (op["ids"] if name == "delete"
                   else self._ids_in_region(table, op["region_mm"], op.get("mode", "inside"),
                                            float(op.get("min_fraction", 0.5))))
            groups = []
            for i in ids:
                i, e = entry(i)
                table[i] = {**e, "kind": "candidate", "reason": "deleted"}
                groups.append([i])
            return groups
        if name == "restore":
            groups = []
            for i in op["ids"]:
                i, e = entry(i, "candidate")
                table[i] = {**e, "kind": "stroke"}
                groups.append([i])
            return groups
        if name in ("move_point", "delete_points", "insert_point", "smooth"):
            i, e = entry(op["id"])
            p = e["poly"]
            if name == "move_point":
                q = edits.move_point(p, op["index"], self.mm_to_px(op["to_mm"]))
            elif name == "delete_points":
                q = edits.delete_points(p, op["indices"])
            elif name == "insert_point":
                q = edits.insert_point(p, op["after_index"], self.mm_to_px(op["at_mm"]))
            else:
                q = edits.smooth(p, op.get("strength", 2))
            table[i] = {**e, "poly": q}
            return [[i]]
        if name == "split":
            i, e = entry(op["id"])
            a, b = edits.split(e["poly"], op["index"])
            nid = alloc()
            table[i] = {**e, "poly": a}
            table[nid] = {"kind": "stroke", "poly": b, "reason": "added"}
            return [[i, nid]]
        if name == "join":
            (a, ea), (b, eb) = entry(op["a"]), entry(op["b"])
            if a == b:
                raise SessionError("서로 다른 두 획을 골라야 합니다")
            table[a] = {**ea, "poly": edits.join(ea["poly"], eb["poly"])}
            table[b] = {**eb, "kind": "gone"}
            return [[a, b]]
        if name == "add_stroke":
            pts = op["points_mm"]
            if not 2 <= len(pts) <= 200:
                raise SessionError("add_stroke는 점 2~200개")
            nid = alloc()
            table[nid] = {"kind": "stroke", "poly": np.array([self.mm_to_px(xy) for xy in pts]), "reason": "added"}
            return [[nid]]
        raise SessionError(f"알 수 없는 편집: {name} (delete, restore, delete_region, move_point, delete_points, "
                           "insert_point, smooth, split, join, add_stroke)")

    def _ids_in_region(self, table, region_mm, mode, min_fraction):
        if mode not in ("inside", "outside"):
            raise SessionError("mode는 inside 또는 outside")
        x0, y0, x1, y1 = self._region_px(region_mm)
        ids = []
        for i, e in table.items():
            if e["kind"] != "stroke":
                continue
            d = edits.densify(e["poly"])
            inside = ((d[:, 0] >= x0) & (d[:, 0] <= x1) & (d[:, 1] >= y0) & (d[:, 1] <= y1)).mean()
            if (inside if mode == "inside" else 1 - inside) >= min_fraction:
                ids.append(i)
        return ids

    # ------------------------------------------------------------ 제안
    def _clear_proposals(self):
        self.pending, self.proposals, self._groups = None, {}, {}

    def _add_group(self, ids):
        merged = set(ids)
        for g in {self.proposals[i]["group"] for i in ids if i in self.proposals}:
            merged |= self._groups.pop(g)
        self._group_seq += 1
        self._groups[self._group_seq] = merged
        for i in merged:
            self.proposals[i] = {"id": i, "group": self._group_seq}

    def propose_edits(self, ops, apply_now=False):
        """편집을 제안 목록에 추가. 하나라도 틀리면 아무것도 바뀌지 않음."""
        with self.lock:
            self._need_result()
            if not isinstance(ops, list) or not ops:
                raise SessionError("ops가 비어 있습니다")
            if len(ops) > edits.MAX_OPS:
                raise SessionError(f"한 번에 편집은 {edits.MAX_OPS}개까지입니다 ({len(ops)}개)")
            table = dict(self.pending if self.pending is not None else self.table)
            counter = [self.next_id]

            def alloc():
                counter[0] += 1
                return counter[0] - 1

            groups = []
            for n, op in enumerate(ops):
                try:
                    groups += self._exec(op, table, alloc)
                except (KeyError, TypeError, ValueError, SessionError) as e:
                    label = op.get("op") if isinstance(op, dict) else op
                    msg = f"필요한 값 {e} 없음" if isinstance(e, KeyError) else str(e)
                    raise SessionError(f"ops[{n}] ({label}): {msg}") from None
            self.pending, self.next_id = table, counter[0]
            for g in groups:
                self._add_group(g)
            created = sorted({i for g in groups for i in g})
            if apply_now:
                return self.apply_proposals(only=created)
            return {"proposed": created, "total": len(self.proposals)}

    def proposal_views(self):
        """제안마다 사라질 모양(before, 빨강)과 생길 모양(after, 초록)."""
        out = []
        for i in sorted(self.proposals):
            old, new = self.table.get(i), self.pending[i]
            before = old["poly"] if old is not None and old["kind"] == "stroke" else None
            after = new["poly"] if new["kind"] == "stroke" else None
            if before is not None and after is before:
                continue
            out.append({"id": i, "before": before, "after": after})
        return out

    def proposal_region_mm(self, ids=None, margin_mm=5.0):
        polys = [p for v in self.proposal_views() if ids is None or v["id"] in ids
                 for p in (v["before"], v["after"]) if p is not None]
        if not polys:
            return None
        mm = self.px_to_mm(np.vstack(polys))
        (x0, y0), (x1, y1) = mm.min(axis=0) - margin_mm, mm.max(axis=0) + margin_mm
        return [float(x0), float(y0), float(x1), float(y1)]

    @staticmethod
    def _find(lst, poly):
        return next((k for k, x in enumerate(lst) if x is poly), None)

    def _record(self, book, old, new):
        """번호 하나의 변화(old -> new)를 모양 기록에 반영."""
        was = old is not None and old["kind"] == "stroke"
        now = new["kind"] == "stroke"
        if was and now and new["poly"] is old["poly"]:
            return
        if (not was and now and old is not None and old["reason"] == "deleted"
                and new["poly"] is old["poly"]):
            k = next((k for k, r in enumerate(book["removed"]) if r["poly"] is old["poly"]), None)
            if k is not None:
                book["removed"].pop(k)      # 지웠던 파이프라인 획을 되살림
                return
        if was:
            k = self._find(book["added"], old["poly"])
            if k is not None:
                book["added"].pop(k)
            else:
                reason = "deleted" if new["kind"] == "candidate" else "replaced"
                book["removed"].append({"poly": old["poly"], "reason": reason})
        if now:
            book["added"].append(new["poly"])

    def apply_proposals(self, exclude=None, only=None):
        with self.lock:
            if not self.proposals:
                raise SessionError("적용할 제안이 없습니다")
            ids = set(self.proposals)
            given = {int(i) for i in (only if only is not None else exclude or [])}
            if given - ids:
                raise SessionError(f"제안에 없는 번호: {sorted(given - ids)[:10]}")
            sel = given if only is not None else ids - given
            apply_ids = set().union(*[g for g in self._groups.values() if g <= sel])
            partial = sorted(sel - apply_ids)
            table = dict(self.table)
            book = {"removed": list(self.book["removed"]), "added": list(self.book["added"])}
            for i in sorted(apply_ids):
                self._record(book, self.table.get(i), self.pending[i])
                table[i] = self.pending[i]
            if not any(e["kind"] == "stroke" for e in table.values()):
                raise SessionError("모든 획을 지울 수는 없습니다 (드로잉에는 획이 1개 이상 필요)")
            desc = f"편집 {len(apply_ids)}건 적용: {sorted(apply_ids)[:20]}"
            self.history.append((self.table, self.book, self.next_id, desc))
            self.table, self.book = table, book
            self._clear_proposals()
            self._refresh_drawing()
            self.edit_log.append(desc)
            note = (f"{partial}번은 다른 번호와 묶인 편집(잇기·자르기)이라 함께 고르지 않아 적용하지 않았습니다"
                    if partial else "")
            return {"applied": sorted(apply_ids), "not_applied": sorted(ids - apply_ids), "note": note}

    def discard_proposals(self, ids=None):
        with self.lock:
            if ids is None:
                n = len(self.proposals)
                self._clear_proposals()
                return n
            drop = set()
            for i in ids:
                if int(i) in self.proposals:
                    drop |= self._groups.pop(self.proposals[int(i)]["group"], set())
            for i in drop:
                self.proposals.pop(i, None)
                self.pending[i] = self.table.get(i, {"kind": "gone", "poly": None, "reason": ""})
            if not self.proposals:
                self._clear_proposals()
            return len(drop)

    def undo(self):
        with self.lock:
            if not self.history:
                return None
            self.table, self.book, self.next_id, desc = self.history.pop()
            self._clear_proposals()
            self._refresh_drawing()
            if self.edit_log:
                self.edit_log.pop()
            return desc

    # ------------------------------------------------------------ 조회
    def list_strokes(self, region_mm=None, include_candidates=False, limit=300):
        with self.lock:
            self._need_result()
            box = self._region_px(region_mm) if region_mm else None
            rows = []
            for i, e in sorted(self.table.items()):
                if e["kind"] == "gone" or (e["kind"] == "candidate" and not include_candidates):
                    continue
                mm = self.px_to_mm(e["poly"])
                (x0, y0), (x1, y1) = mm.min(axis=0), mm.max(axis=0)
                if box:
                    px0, py0 = e["poly"].min(axis=0)
                    px1, py1 = e["poly"].max(axis=0)
                    if px1 < box[0] or px0 > box[2] or py1 < box[1] or py0 > box[3]:
                        continue
                rows.append({"id": i, "kind": e["kind"], "reason": e["reason"],
                             "length_mm": round(float(np.hypot(*np.diff(mm, axis=0).T).sum()), 1),
                             "bbox_mm": [round(float(v), 1) for v in (x0, y0, x1, y1)], "points": len(mm)})
            return {"rows": rows[:limit], "truncated": len(rows) > limit, "total": len(rows)}

    def get_stroke(self, stroke_id, limit=400):
        with self.lock:
            self._need_result()
            e = self.table.get(int(stroke_id))
            if e is None or e["kind"] == "gone":
                raise SessionError(f"없는 번호: {stroke_id}")
            mm = self.px_to_mm(e["poly"])
            pts = [[k, round(float(x), 2), round(float(y), 2)] for k, (x, y) in enumerate(mm[:limit])]
            return {"id": int(stroke_id), "kind": e["kind"], "reason": e["reason"], "points_mm": pts,
                    "truncated": len(mm) > limit}
```

`state()`의 `"result"` 안의 `"edits": list(self.edit_log)`는 유지하고, 그 아래에 추가한다.

```python
                s["edit"] = {
                    "proposals": [{"id": v["id"], "change": ("delete" if v["after"] is None else
                                                              "add" if v["before"] is None else "modify")}
                                  for v in self.proposal_views()],
                    "strokes": sum(1 for e in self.table.values() if e["kind"] == "stroke"),
                    "candidates": sum(1 for e in self.table.values() if e["kind"] == "candidate"),
                    "unapplied_edits": self.unapplied,
                    "notice": self.notice,
                }
```

- [ ] **Step 4: 통과 확인**

Run: `cd tests && python -m unittest test_agent -v`
Expected: `EditSessionTest` 전부 PASS. `ToolboxTest`·MCP 테스트 중 `delete_strokes`를 쓰는 것은 아직 실패한다(다음 작업에서 도구를 바꾼다). 이 작업에서는 그 두 테스트의 `delete_strokes`를 `undo`로 임시로 바꾸지 말고, Task 10과 함께 커밋한다. 이 작업의 커밋은 Task 11 Step 4 이후로 미룬다.

---

### Task 10: 초록/빨강·번호 그림 (에이전트용 `view(edit)`)

**Files:**
- Modify: `mirobot_sketch/edits.py` (렌더러 추가)
- Modify: `mirobot_sketch/session.py` (`render("edit", ...)`)
- Test: `tests/test_edits.py`, `tests/test_agent.py`

**Interfaces:**
- Produces:
  - `edits.render_edit_view(shape, table, views, region_px=None, numbered=True, show_candidates=False, original=None, alpha=0.0, max_px=1000) -> BGR`
    - `views`는 `proposal_views()` 형식이다.
  - `SketchSession.render(kind, region_mm=None, numbered=False, max_px=1000, show_candidates=False, overlay=0.0)`
    - `edit`는 `numbered` 기본값이 True다(도구에서 지정).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_edits.py`)

```python
class RenderTest(unittest.TestCase):
    def test_proposals_are_green_and_red(self):
        table = {1: {"kind": "stroke", "poly": np.array([[10, 50], [190, 50]], float), "reason": ""},
                 2: {"kind": "candidate", "poly": np.array([[10, 150], [190, 150]], float), "reason": "small"}}
        views = [{"id": 1, "before": table[1]["poly"], "after": None},
                 {"id": 2, "before": None, "after": table[2]["poly"]}]
        img = edits.render_edit_view((200, 200), table, views, max_px=200)
        self.assertEqual(tuple(int(v) for v in img[50, 100]), edits.RED)
        self.assertEqual(tuple(int(v) for v in img[150, 100]), edits.GREEN)

    def test_candidates_hidden_unless_asked(self):
        table = {1: {"kind": "candidate", "poly": np.array([[10, 100], [190, 100]], float), "reason": "small"}}
        hidden = edits.render_edit_view((200, 200), table, [], max_px=200)
        shown = edits.render_edit_view((200, 200), table, [], show_candidates=True, max_px=200)
        self.assertTrue((hidden == 255).all())
        self.assertFalse((shown == 255).all())
```

`test_agent.py`의 `EditSessionTest`에 추가한다.

```python
    def test_render_edit_region_and_overlay(self):
        s = self.new_session()
        img = s.render("edit", region_mm=[-10, -10, 10, 10], numbered=True, show_candidates=True, overlay=0.5)
        self.assertEqual(img.ndim, 3)
        self.assertLessEqual(max(img.shape[:2]), 1000)
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_edits.RenderTest -v`
Expected: FAIL — `AttributeError: module 'mirobot_sketch.edits' has no attribute 'render_edit_view'`

- [ ] **Step 3: 구현** (`edits.py` 끝)

```python
LABEL_MIN_PX = 20        # 화면에서 이보다 짧은 획은 번호를 붙이지 않음
LABEL_MAX = 400          # 번호 딱지 최대 개수 (제안 딱지는 항상)


def _label(img, text, xy, color):
    x, y = int(xy[0]) + 3, int(xy[1]) - 3
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)


def _dashed(img, pts, color):
    for k, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
        if k % 2 == 0:
            cv2.line(img, tuple(a), tuple(b), color, 1, cv2.LINE_AA)


def render_edit_view(shape, table, views, region_px=None, numbered=True, show_candidates=False,
                     original=None, alpha=0.0, max_px=1000):
    """편집 화면: 획(회색), 후보(연회색 점선), 제안(빨강=사라짐, 초록=생김)과 번호."""
    h, w = shape[:2]
    x0, y0, x1, y1 = region_px if region_px else (0, 0, w, h)
    x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1)
    scale = max_px / max(x1 - x0, y1 - y0, 1.0)
    W, H = max(1, int((x1 - x0) * scale)), max(1, int((y1 - y0) * scale))
    img = np.full((H, W, 3), 255, np.uint8)
    if original is not None and alpha > 0:
        crop = original[int(y0):int(np.ceil(y1)), int(x0):int(np.ceil(x1))]
        if crop.size:
            crop = cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA)
            img = (crop.astype(np.float32) * alpha + 255 * (1 - alpha)).astype(np.uint8)

    def to_px(p):
        return np.round((np.asarray(p) - (x0, y0)) * scale).astype(np.int32)

    def visible(q):
        return ((q[:, 0] >= 0) & (q[:, 0] < W) & (q[:, 1] >= 0) & (q[:, 1] < H)).any()

    labels = []
    for i, e in sorted(table.items()):
        if e["kind"] == "candidate" and show_candidates:
            q = to_px(densify(e["poly"], 3.0))
            if visible(q):
                _dashed(img, q, CANDIDATE)
                labels.append((i, q, CANDIDATE))
        elif e["kind"] == "stroke":
            q = to_px(e["poly"])
            if visible(q):
                cv2.polylines(img, [q.reshape(-1, 1, 2)], False, INK, 1, cv2.LINE_AA)
                labels.append((i, q, INK))
    if numbered:
        drawn = 0
        for i, q, color in labels:
            if drawn >= LABEL_MAX:
                break
            if np.hypot(*np.diff(q, axis=0).T).sum() >= LABEL_MIN_PX:
                _label(img, str(i), q[len(q) // 2], color)
                drawn += 1
    for v in views:   # 제안은 굵게(3px, 계단 없는 굵기라 LINE_8로 색을 정확히), 번호 딱지는 항상
        for key, color in (("before", RED), ("after", GREEN)):
            if v[key] is not None:
                q = to_px(v[key])
                cv2.polylines(img, [q.reshape(-1, 1, 2)], False, color, 3, cv2.LINE_8)
        q = to_px(v["after"] if v["after"] is not None else v["before"])
        _label(img, str(v["id"]), q[len(q) // 2], GREEN if v["after"] is not None else RED)
    return img
```

`session.render`의 `edit` 분기를 다음으로 바꾼다(시그니처에 `show_candidates=False, overlay=0.0` 추가).

```python
            if kind == "edit":
                region_px = self._region_px(region_mm) if region_mm else None
                views = self.proposal_views() if self.proposals else []
                return edits.render_edit_view(r["base"].shape, self.table, views, region_px, numbered,
                                              show_candidates, self.color, float(overlay), max_px)
```

- [ ] **Step 4: 통과 확인**

Run: `cd tests && python -m unittest test_edits test_agent.EditSessionTest -v`
Expected: PASS

---

### Task 11: 에이전트 도구 — 목록·점 좌표·제안·적용

**Files:**
- Modify: `mirobot_sketch/agent/tools.py`
- Test: `tests/test_agent.py` (`ToolboxTest`, MCP 테스트)

**Interfaces:**
- Consumes: 세션의 `propose_edits`, `apply_proposals`, `discard_proposals`, `list_strokes`, `get_stroke`, `proposal_region_mm`, `render(... show_candidates, overlay)`
- Produces: 도구 이름 목록 `get_state, view, set_params, list_strokes, get_stroke, propose_edits, apply_proposals, discard_proposals, undo, simulate`. `delete_strokes`, `delete_region`은 지운다.

- [ ] **Step 1: 실패하는 테스트 작성**

`ToolboxTest.test_errors_are_returned_not_raised`의 `("delete_strokes", {"wrong": 1})`를 `("propose_edits", {"wrong": 1})`로 바꾸고, MCP 테스트의 4번 호출을 다음으로 바꾼다.

```python
            r = rpc(4, "tools/call", {"name": "propose_edits",
                                      "arguments": {"ops": [{"op": "delete", "ids": [10 ** 6]}]}})
```

아래 테스트를 추가한다.

```python
    def test_propose_view_apply_flow(self):
        changes = []
        s = self.new_session()
        tb = AgentToolbox(s, on_change=changes.append)
        rows = json.loads(tb.call("list_strokes", {"include_candidates": True})[0][0]["text"])["rows"]
        stroke = next(r["id"] for r in rows if r["kind"] == "stroke")
        parts, err = tb.call("propose_edits", {"ops": [{"op": "delete", "ids": [stroke]}]})
        self.assertFalse(err, parts)
        self.assertEqual([p["type"] for p in parts], ["text", "image"])       # 바뀌는 부위 미리보기
        self.assertIn("proposals", changes)
        parts, err = tb.call("apply_proposals", {})
        self.assertFalse(err, parts)
        self.assertEqual(s.table[stroke]["kind"], "candidate")
        parts, err = tb.call("view", {"kind": "edit", "show_candidates": True, "overlay_original": 0.4})
        self.assertFalse(err)
        pts = json.loads(tb.call("get_stroke", {"id": stroke})[0][0]["text"])["points_mm"]
        self.assertEqual(pts[0][0], 0)

    def test_old_delete_tools_are_gone(self):
        names = {t["name"] for t in TOOLS}
        self.assertFalse(names & {"delete_strokes", "delete_region"})
        self.assertTrue({"list_strokes", "get_stroke", "propose_edits", "apply_proposals",
                         "discard_proposals"} <= names)
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_agent.ToolboxTest -v`
Expected: FAIL — `알 수 없는 도구: list_strokes`

- [ ] **Step 3: 구현**

`TOOLS`에서 `delete_strokes`, `delete_region`을 지운다. `view`의 properties에 아래 두 항목을 더하고, description 끝에 문장 하나를 붙인다.

```python
                "show_candidates": {"type": "boolean", "description": "edit에서 버린 선(살릴 후보)을 회색 점선과 번호로"},
                "overlay_original": {"type": "number", "minimum": 0, "maximum": 1,
                                     "description": "edit에서 컬러 원본을 비치게 (0~1, 빠진 선 찾기에 좋음)"},
```

description에 붙일 문장: `" edit는 현재 획(회색)과 번호, 제안(빨강=사라짐, 초록=생김)을 보여 줍니다."`

새 도구는 `undo` 앞에 넣는다.

```python
    {
        "name": "list_strokes",
        "description": "획(과 후보)의 표: 번호, 종류(stroke/candidate), 이유(small 작은 덩어리, spur 잔가지, "
                       "overlap 겹침, deleted 지운 획, added 추가), 길이 mm, 테두리 상자 mm, 점 수. "
                       "region_mm로 좁히면 편합니다. 최대 300줄.",
        "parameters": {"type": "object", "properties": {
            "region_mm": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            "include_candidates": {"type": "boolean"}}, "additionalProperties": False},
    },
    {
        "name": "get_stroke",
        "description": "획 하나의 점 좌표 [점 번호, x_mm, y_mm] (최대 400점). 점 편집 전에 확인하세요.",
        "parameters": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"],
                       "additionalProperties": False},
    },
    {
        "name": "propose_edits",
        "description": (
            "편집을 제안합니다(바로 적용되지 않음). 화면에 빨강(사라짐)·초록(생김)과 번호로 표시되고, "
            "바뀌는 부위를 확대한 그림을 돌려줍니다. 하나라도 틀리면 아무것도 바뀌지 않습니다. 최대 200개.\n"
            "ops 항목: {op:'delete', ids:[...]} | {op:'restore', ids:[후보 번호]} | "
            "{op:'delete_region', region_mm:[x0,y0,x1,y1], mode:'inside'|'outside'} | "
            "{op:'move_point', id, index, to_mm:[x,y]} | {op:'delete_points', id, indices:[...]} | "
            "{op:'insert_point', id, after_index, at_mm:[x,y]} | {op:'smooth', id, strength:1~5} | "
            "{op:'split', id, index} | {op:'join', a, b} | {op:'add_stroke', points_mm:[[x,y],...]}\n"
            "apply_now=true는 사용자가 '바로 해'라고 했을 때만 쓰세요."
        ),
        "parameters": {"type": "object", "properties": {
            "ops": {"type": "array", "minItems": 1, "maxItems": 200,
                    "items": {"type": "object", "properties": {"op": {"type": "string", "enum": [
                        "delete", "restore", "delete_region", "move_point", "delete_points", "insert_point",
                        "smooth", "split", "join", "add_stroke"]}}, "required": ["op"]}},
            "apply_now": {"type": "boolean"}}, "required": ["ops"], "additionalProperties": False},
    },
    {
        "name": "apply_proposals",
        "description": "제안을 적용합니다. 모두 적용하거나, exclude=[번호]로 빼거나, only=[번호]만. "
                       "잇기·자르기로 묶인 번호는 함께 골라야 적용됩니다. 적용 후 제안 목록은 비워집니다.",
        "parameters": {"type": "object", "properties": {
            "exclude": {"type": "array", "items": {"type": "integer"}},
            "only": {"type": "array", "items": {"type": "integer"}}}, "additionalProperties": False},
    },
    {
        "name": "discard_proposals",
        "description": "제안을 취소합니다. ids를 빼면 전부.",
        "parameters": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}}},
                       "additionalProperties": False},
    },
```

`undo`의 description은 `"마지막으로 적용한 편집을 되돌립니다."`로 바꾼다.

도구 구현에서 `_delete_strokes`, `_delete_region`을 지우고 아래를 추가한다. `_view`는 교체한다.

```python
    def _view(self, kind, numbered=None, region_mm=None, show_candidates=False, overlay_original=0.0):
        numbered = (kind == "edit") if numbered is None else numbered
        img = self.session.render(kind, region_mm=region_mm, numbered=numbered,
                                  show_candidates=show_candidates, overlay=overlay_original)
        label = f"{kind}" + (" (번호)" if numbered else "") + (f" 영역 {region_mm}" if region_mm else "")
        return [text_part(f"그림: {label}"), image_part(img)]

    def _list_strokes(self, region_mm=None, include_candidates=False):
        return [text_part(self.session.list_strokes(region_mm, include_candidates))]

    def _get_stroke(self, id):
        return [text_part(self.session.get_stroke(id))]

    def _propose_edits(self, ops, apply_now=False):
        s = self.session
        out = s.propose_edits(ops, apply_now=apply_now)
        self.on_change("result" if apply_now else "proposals")
        if apply_now:
            return [text_part({**out, "result": s.state().get("result")})]
        region = s.proposal_region_mm(out["proposed"])
        parts = [text_part({**out, "legend": "빨강=사라짐, 초록=생김, 숫자=번호"})]
        if region:
            parts.append(image_part(s.render("edit", region_mm=region, numbered=True, overlay=0.3)))
        return parts

    def _apply_proposals(self, exclude=None, only=None):
        out = self.session.apply_proposals(exclude=exclude, only=only)
        self.on_change("result")
        return [text_part({**out, "result": self.session.state().get("result")})]

    def _discard_proposals(self, ids=None):
        n = self.session.discard_proposals(ids)
        self.on_change("proposals")
        return [text_part({"discarded": n})]
```

`SYSTEM_PROMPT`의 "작업 방식"을 다음으로 바꾼다.

```text
작업 방식
- 먼저 get_state로 현재 상태를 보고, view로 원본과 결과를 눈으로 확인하세요.
- 설정을 바꾼 뒤에는 view로 결과를 다시 확인하고, 획 수·예상 시간의 변화를 사용자에게 알려 주세요.
- 선을 다듬을 때:
  1) view(kind="edit", overlay_original=0.4, show_candidates=true)로 원본 위의 획과 버린 선(후보)을 봅니다.
  2) 문제 부위는 region_mm로 확대하고, list_strokes로 번호·이유를 확인합니다.
  3) propose_edits로 제안하고 돌려받은 그림(빨강=사라짐, 초록=생김)으로 스스로 검토합니다.
  4) 사용자에게 "초록 813·820은 머리카락 윤곽을 살리고, 빨강 5·8은 배경 잡음을 지웁니다"처럼 번호로 설명하고
     확인을 기다립니다. 사용자가 "5번 빼고 적용"이라 하면 apply_proposals(exclude=[5]).
  사용자가 바로 하라고 했을 때만 apply_now=true를 쓰세요.
- 점 편집(move_point 등)은 get_stroke로 점 번호와 좌표를 확인한 뒤에 하세요.
- 설정을 바꿔 다시 계산하면 번호가 새로 매겨지고 적용 전 제안은 취소됩니다(적용한 편집은 유지).
  설정을 먼저 정하고 편집은 마지막에 하세요.
- 좌표는 종이 중심이 원점인 mm이며 x는 오른쪽, y는 위쪽이 +입니다. ±60mm 밖은 거부됩니다.
```

- [ ] **Step 4: 전체 통과 확인**

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK (MCP 전체 경로 포함)

- [ ] **Step 5: 커밋 (Task 9·10·11 함께)**

```bash
git add mirobot_sketch/session.py mirobot_sketch/edits.py mirobot_sketch/agent/tools.py tests/test_agent.py tests/test_edits.py
git commit -m "Edit proposals: numbered table with restore candidates, point edits, green/red previews, agent tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: GUI — 편집 단계 그림, 번호 딱지, 제안 바

**Files:**
- Modify: `mirobot_sketch/stage_view.py` (`ProposalBar` 추가)
- Modify: `mirobot_sketch/gui.py` (편집 단계 벡터 그림, 옵션 체크박스, 제안 바 연결)
- Test: `tests/test_gui_smoke.py`

**Interfaces:**
- Consumes:
  - `session.table`, `session.proposal_views()`, `session.apply_proposals()`, `session.discard_proposals()`
  - `BigView.options_frame`, `BigView.on_view_change`, `BigView.view_rect()`
- Produces:
  - `stage_view.ProposalBar(master, font, on_apply, on_discard)`: `.update(views)`, `.excluded: set`
  - `SketchApp._draw_edit(ax)`, `SketchApp.refresh_proposals()`

- [ ] **Step 1: 실패하는 스모크 테스트 추가**

```python
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
                self.assertTrue(app.proposal_bar.winfo_ismapped())
                self.assertIn(sid, app.proposal_bar.chips)
                app.proposal_bar.apply_btn.invoke()
                root.update()
                self.assertEqual(s.table[sid]["kind"], "candidate")
                self.assertFalse(app.proposal_bar.winfo_ismapped())
        finally:
            app._on_close()
```

- [ ] **Step 2: 실패 확인**

Run: `cd tests && python -m unittest test_gui_smoke -v`
Expected: FAIL — `AttributeError: 'SketchApp' object has no attribute 'refresh_proposals'`

- [ ] **Step 3: `ProposalBar` 구현** (`stage_view.py` 끝)

```python
GREEN_TXT, RED_TXT = "#16a34a", "#dc2626"
MAX_CHIPS = 40


class ProposalBar(ctk.CTkFrame):
    """제안 n건 🟢a 🔴b [적용] [취소] + 번호 딱지(눌러서 빼기/넣기)."""

    def __init__(self, master, font, on_apply, on_discard):
        super().__init__(master, fg_color=("#f3f6fb", "#1b2029"), corner_radius=12)
        self.font, self.excluded, self.chips = font, set(), {}
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 2))
        self.summary = ctk.CTkLabel(top, text="", font=font(13, "bold"))
        self.summary.pack(side="left")
        self.discard_btn = ctk.CTkButton(top, text="취소", width=60, height=28, font=font(12),
                                         fg_color="transparent", border_width=1, text_color=TEXT,
                                         command=on_discard)
        self.discard_btn.pack(side="right", padx=(6, 0))
        self.apply_btn = ctk.CTkButton(top, text="적용", width=80, height=28, font=font(12, "bold"),
                                       fg_color=ACCENT, command=lambda: on_apply(sorted(self.excluded)))
        self.apply_btn.pack(side="right")
        self.chip_row = ctk.CTkScrollableFrame(self, orientation="horizontal", height=34, fg_color="transparent")
        self.chip_row.pack(fill="x", padx=6, pady=(0, 6))

    def update(self, views):
        for w in self.chip_row.winfo_children():
            w.destroy()
        self.chips = {}
        ids = {v["id"] for v in views}
        self.excluded &= ids
        adds = sum(1 for v in views if v["after"] is not None)
        dels = sum(1 for v in views if v["after"] is None)
        self.summary.configure(text=f"제안 {len(views)}건   🟢 {adds}   🔴 {dels}")
        for v in views[:MAX_CHIPS]:
            color = GREEN_TXT if v["after"] is not None else RED_TXT
            b = ctk.CTkButton(self.chip_row, text=f"#{v['id']}", width=52, height=26, font=self.font(12, "bold"),
                              fg_color="transparent", border_width=2, border_color=color, text_color=color,
                              command=lambda i=v["id"]: self._toggle(i))
            b.pack(side="left", padx=2)
            self.chips[v["id"]] = b
        if len(views) > MAX_CHIPS:
            ctk.CTkLabel(self.chip_row, text=f"… 외 {len(views) - MAX_CHIPS}건", font=self.font(11),
                         text_color=MUTED).pack(side="left", padx=4)
        for i in self.excluded:
            self._style(i)

    def _toggle(self, i):
        self.excluded ^= {i}
        self._style(i)

    def _style(self, i):
        b = self.chips.get(i)
        if b is not None:
            b.configure(fg_color=("#e5e7eb", "#374151") if i in self.excluded else "transparent",
                        text=f"#{i}" + (" 뺌" if i in self.excluded else ""))
```

- [ ] **Step 4: `gui.py` 연결**

import에 `from matplotlib.collections import LineCollection`과 `ProposalBar`를 더한다. `_build_ui`의 `self.view` 생성 뒤에 아래를 넣는다.

```python
        self.show_numbers = tk.BooleanVar(value=True)
        self.show_cands = tk.BooleanVar(value=False)
        for text, var in (("번호", self.show_numbers), ("버린 선", self.show_cands)):
            ctk.CTkCheckBox(self.view.options_frame, text=text, variable=var, font=font(11), width=20,
                            command=self.view.redraw).pack(side="left", padx=4)
        self.view.on_view_change = self.view.redraw     # 확대·이동하면 보이는 획만 번호를 다시 붙임
        self.proposal_bar = ProposalBar(view_card, font, self._apply_proposals, self._discard_proposals)
```

`_show_stage`의 결과 분기를 편집 단계용으로 바꾼다.

```python
        overlay = None if self.stage_id in ("source", "paper") else s.color
        if self.stage_id == "edit":
            blank = np.full((*s.result["base"].shape, 3), 255, np.uint8)
            self.view.show("편집 (빨강=사라짐 · 초록=생김)", blank, overlay, draw_extra=self._draw_edit)
        else:
            self.view.show(st.label, s.render(self.stage_id), overlay)
        # 번호·버린 선 체크박스는 편집 단계에서만 보임
        if self.stage_id == "edit":
            self.view.options_frame.pack(side="right", padx=8)
        else:
            self.view.options_frame.pack_forget()
```

`gui.py`에 `import numpy as np`를 더한다(없으면).

벡터 그림과 제안 바 메서드:

```python
    def _draw_edit(self, ax):
        s = self.session
        ink = "#374151"   # 편집 그림은 흰 바탕(종이)이라 테마와 상관없이 진한 회색
        x0, y0, x1, y1 = self.view.view_rect()
        box = ax.get_window_extent()
        px_per_unit = box.width / max(x1 - x0, 1e-6)
        strokes, cands, labels = [], [], []
        for i, e in sorted(s.table.items()):
            if e["kind"] == "stroke":
                strokes.append(e["poly"])
                labels.append((i, e["poly"], ink))
            elif e["kind"] == "candidate" and self.show_cands.get():
                cands.append(e["poly"])
                labels.append((i, e["poly"], "#9ca3af"))
        ax.add_collection(LineCollection(strokes, colors=ink, linewidths=0.9))
        if cands:
            ax.add_collection(LineCollection(cands, colors="#9ca3af", linewidths=0.8, linestyles="dashed"))
        views = s.proposal_views() if s.proposals else []
        for v in views:
            if v["before"] is not None:
                ax.plot(v["before"][:, 0], v["before"][:, 1], color="#dc2626", linewidth=2.6)
            if v["after"] is not None:
                ax.plot(v["after"][:, 0], v["after"][:, 1], color="#16a34a", linewidth=2.6)
        if self.show_numbers.get():
            n = 0
            for i, poly, color in labels:
                if n >= 400:
                    break
                mid = poly[len(poly) // 2]
                if not (x0 <= mid[0] <= x1 and y0 <= mid[1] <= y1):
                    continue
                if np.hypot(*np.diff(poly, axis=0).T).sum() * px_per_unit < 20:
                    continue
                ax.text(mid[0], mid[1], str(i), fontsize=8, color=color, clip_on=True)
                n += 1
        for v in views:
            poly = v["after"] if v["after"] is not None else v["before"]
            mid = poly[len(poly) // 2]
            ax.text(mid[0], mid[1], str(v["id"]), fontsize=9, fontweight="bold", clip_on=True,
                    color="white", bbox={"boxstyle": "round,pad=0.2", "lw": 0,
                                         "fc": "#16a34a" if v["after"] is not None else "#dc2626"})

    def refresh_proposals(self):
        views = self.session.proposal_views() if self.session.proposals else []
        if views:
            self.proposal_bar.update(views)
            self.proposal_bar.pack(fill="x", padx=8, pady=(0, 8))
        else:
            self.proposal_bar.pack_forget()
        if self.stage_id == "edit":
            self.view.redraw()

    def _apply_proposals(self, exclude):
        try:
            out = self.session.apply_proposals(exclude=exclude)
        except Exception as e:
            messagebox.showerror("적용 실패", str(e))
            return
        self._show_result(self.session.result, status=f"편집 {len(out['applied'])}건 적용. {out['note']}".strip())
        self.refresh_proposals()

    def _discard_proposals(self):
        self.session.discard_proposals()
        self.refresh_proposals()
```

`_show_result` 끝에 `self.refresh_proposals()`를 넣는다. `_refresh_from_session`은 `what == "proposals"`이면 `self.refresh_proposals()`만 부르고 나머지는 지금처럼 둔다.

```python
    def _refresh_from_session(self, what="result"):
        if what == "proposals":
            self.refresh_proposals()
            return
        # (기존 본문)
```

상태 줄에는 세션 알림(번호를 새로 매김, 제안 취소)을 보여 준다. `_show_result`의 마지막 `_set_status` 호출을 다음으로 바꾼다.

```python
        notice = self.session.notice
        self.session.notice = ""
        self._set_status(status + (f" (획 편집 {edits}건)" if edits else "") + (f"\n{notice}" if notice else ""))
```

- [ ] **Step 5: 통과 확인**

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK

- [ ] **Step 6: 직접 보고 확인**

스크래치 스크립트로 illust1을 열고, 제안 몇 개를 만든다(`delete` 2개, 후보 `restore` 1개, `smooth` 1개). 편집 단계를 확대한 상태로 `app.view.fig.savefig`한 이미지를 라이트/다크 모두 직접 본다. 확인할 것:
- 빨강·초록 선과 번호 딱지
- 확대했을 때 보이는 획에만 번호가 붙는지
- 제안 바의 딱지를 눌러 뺀 뒤 적용한 결과

- [ ] **Step 7: 커밋**

```bash
git add mirobot_sketch/stage_view.py mirobot_sketch/gui.py tests/test_gui_smoke.py
git commit -m "GUI edit stage: vector strokes with view-aware numbers, candidates, green/red proposals, proposal bar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: 속도 측정, 문서, 기록

**Files:**
- Modify: `tests/golden.py` (`--perf`)
- Modify: `docs/superpowers/specs/2026-09-26-stage-pipeline-edit-proposals-design.md` (계획 단계에서 정한 수정 반영)
- Modify: `README.md` (GUI 사용법의 단계·편집 부분)
- Create: `LOG/2026-09-26-stage-pipeline.md`
- Modify: `LOG/README.md`

- [ ] **Step 1: `--perf` 구현** (`golden.py`의 `main()` 안, `if args.write:` 다음)

```python
    if args.perf:
        import time

        from mirobot_sketch import stages
        for fname in SAMPLE_TYPES:
            p = ROOT / "input" / fname
            if not p.exists():
                continue
            gray = sp.load_gray(p)
            inp = {"gray": gray, "color": sp.load_color(p)}
            pl, prm = stages.Pipeline(), stages.default_params()
            t0 = time.perf_counter()
            pl.run(inp, fname, prm)
            full = time.perf_counter() - t0
            t0 = time.perf_counter()
            pl.run(inp, fname, {**prm, "epsilon_px": 2.0})
            late = time.perf_counter() - t0
            print(f"{fname}: 전체 {full:.2f}s, 단순화만 {late:.3f}s")
```

- [ ] **Step 2: 측정**

Run: `python tests/golden.py --perf`
Expected:
- 이미지마다 "전체 ≤ 2.5s, 단순화만 ≤ 0.3s"
- 첫 이미지는 skimage 로딩 때문에 느릴 수 있다. 목표를 넘으면 LOG에 수치와 원인을 적는다.

- [ ] **Step 3: spec 수정 반영**

설계 문서를 계획의 "Spec 수정"대로 고친다.
- §4 마지막 줄: 파이프라인 결과가 바뀌면 적용 전 제안은 취소하고 알린다. 종이 크기만 바뀌면 유지한다.
- §3 번호: 지운 획은 같은 번호의 후보(deleted)가 되고, join으로 사라진 획은 `gone`이 된다.
- §4: join·split은 묶음이다.

- [ ] **Step 4: README와 LOG**

README의 GUI 설명에 세 가지를 짧게 적는다. 기존 문서 문체를 따른다.
- 단계 띠와 자동 재계산
- 원본 겹치기
- 편집 단계의 번호, 제안 바, 에이전트 편집 흐름

`LOG/2026-09-26-stage-pipeline.md`는 기존 LOG 형식(문제 → 해결 → 확인 → 한계)으로 쓴다. 들어갈 내용:
- 기준값 비교 결과
- `--perf` 수치
- Lab 검출 전후 예시 수치: illust1에서 luma와 lab의 획 수
- 편집 흐름 확인
- 라이트/다크 캡처 확인
- 남은 한계: 마우스 손 편집은 하위 프로젝트 4에서 다룬다.

`LOG/README.md` 목록에 링크를 추가한다.

- [ ] **Step 5: 최종 확인**

Run: `python -m unittest discover -s tests && python -m pyflakes mirobot_sketch tests`
Expected: OK

- [ ] **Step 6: 커밋**

```bash
git add tests/golden.py docs/superpowers/specs/2026-09-26-stage-pipeline-edit-proposals-design.md README.md LOG/2026-09-26-stage-pipeline.md LOG/README.md
git commit -m "Measure stage pipeline speed, update spec, README and LOG

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
