# 얼굴 섬세하게 그리기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실사 사진에서 얼굴을 찾아 (B) 얼굴이 작으면 자동으로 상반신 구도로 자르고, (A) 얼굴 영역만 원본 해상도로 다시 선을 찾아 펜 굵기에 맞는 밀도로 끼워 넣는다.

**Architecture:**
- `faces.py`가 검출(YuNet)과 구도 계산을 맡는다.
- `session._inputs`가 원본 해상도에서 구도를 자르고 얼굴 정보·고해상도 얼굴 조각을 입력에 넣는다.
- 새 파이프라인 단계 `face`가 "이어 붙이기" 다음에 얼굴 타원 안의 획을 교체한다.

**Tech Stack:** OpenCV `FaceDetectorYN`(YuNet ONNX), numpy, 기존 stages/session 구조, unittest

**Spec:** `docs/superpowers/specs/2026-09-26-face-detail-design.md`

## Global Constraints
- **모델 파일:** `mirobot_sketch/data/face_detection_yunet_2023mar.onnx`(232,589바이트, SHA256 `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`, MIT). `THIRD_PARTY_NOTICES.md`에 표기한다.
- **검출:** 신뢰도 0.7, 얼굴 폭이 짧은 변의 3% 미만이면 버린다. 실패하면 조용히 `[]`를 돌려준다.
- **구도 기본값:** `frame=auto`. 종이 위 얼굴 높이 < 25mm이고 얼굴이 정확히 1개일 때만 `bust`를 쓴다.
- **얼굴 단계 기본값:** `face_detail=True`, `face_sensitivity=0.6`, `pen_mm=0.5`. 얼굴이 없으면 입력을 그대로 넘긴다.
- **변경 없음:** 얼굴이 없는 이미지(합성 이미지·애니)는 결과가 지금과 같아야 한다(골든 기준값 유지).
- **테스트:** `python -m unittest discover -s tests` 전부 통과, pyflakes 깨끗. 테스트는 실제 사진 없이 돈다(`input/`이 있을 때만 추가 확인).
- **커밋:** 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. 브랜치는 `feature/face-detail`이다(`feature/smooth-strokes` 위).

## Review Focus
1. **자동 구도 틀이 box_mm 변경으로 바뀜:** 편집 기록을 비우고 알려야 한다. 틀이 그대로면 편집을 유지해야 한다. → Task 3
2. **얼굴 타원 경계를 지나는 긴 획(머리카락·어깨선):** 경계에서 잘려 바깥 부분은 남아야 한다. 통째로 사라지면 안 된다. → Task 4
3. **얼굴 상자가 이미지 가장자리에 걸침(photo1은 위쪽이 음수):** 자르기와 되돌리기 좌표가 어긋나지 않아야 한다. → Task 2, 4
4. **배경 제거(rembg)와 구도를 함께 켬:** rembg 결과(원본 크기)를 자르고, 캐시 키가 섞이지 않아야 한다. → Task 3
5. **모델이 없는 환경(오래된 OpenCV, 파일 누락):** 앱이 죽지 않고 얼굴 없음으로 동작해야 한다. → Task 1

---

### Task 1: 얼굴 검출 `faces.py` + 모델 포함

**Files:**
- Create: `mirobot_sketch/faces.py`, `mirobot_sketch/data/face_detection_yunet_2023mar.onnx`, `THIRD_PARTY_NOTICES.md`
- Modify: `pyproject.toml`(package-data `data/*.onnx`)
- Test: `tests/test_faces.py`

**Interfaces:**
- Produces:
  - `Face(box: np.ndarray[4] (x, y, w, h), landmarks: np.ndarray[5, 2], score: float)`. `Face.scaled(k, dx=0, dy=0)`는 좌표를 `p*k + (dx, dy)`로 옮긴 새 Face다.
  - `detect_faces(bgr, min_score=0.7, detector=None) -> list[Face]`: 신뢰도 내림차순. `detector`는 테스트용으로 `(img) -> (N×15 배열 | None)`을 주입한다.
  - `MODEL_PATH`

- [ ] Step 1: 실패 테스트
  - 모델 파일이 있고 크기·SHA256이 맞다.
  - 모델이 불러와진다(`FaceDetectorYN`이 없으면 skip). 빈 흰 이미지 → `[]`
  - 가짜 detector로 확인:
    - 1600px 이미지에서 800px로 줄여 검출한 좌표가 원래 크기로 돌아온다(×2).
    - 신뢰도 0.5는 버린다.
    - 짧은 변의 3% 미만 폭은 버린다.
    - 순서는 신뢰도 내림차순이다.
  - `MODEL_PATH`를 없는 파일로 바꾸면 `[]`
  - `input/photo2_stage.jpg`가 있으면 얼굴 1개, 애니 `input/illust1_color.jpg`는 0개(없으면 skip)
- [ ] Step 2: 실행 → FAIL(ImportError)
- [ ] Step 3: 구현
  - 모델을 scratchpad에서 `mirobot_sketch/data/`로 복사한다.
  - `_yunet(size)`는 `cv2.FaceDetectorYN.create(str(MODEL_PATH), "", size, min_score, 0.3, 50)`이다.
  - `cv2.utils.logging.setLogLevel`로 경고를 감추고 원래 수준으로 되돌린다.
  - 모든 예외는 `[]`로 처리한다.
- [ ] Step 4: 통과, pyflakes → 커밋

### Task 2: 구도 계산 (`faces.frame_box`, `faces.choose_frame`)

**Files:** Modify `mirobot_sketch/faces.py`; Test `tests/test_faces.py`

**Interfaces:**
- Produces:
  - `frame_box(face, kind, img_w, img_h) -> (x0, y0, x1, y1) int`: kind는 `"bust"` 또는 `"face"`. 틀은 이미지 안으로 밀어 넣고, 이미지보다 크면 줄인다.
  - `choose_frame(faces, img_w, img_h, box_mm, frame) -> (kind, box | None, notice)`
    - `frame`: auto | full | bust | face
    - `kind`: 실제로 쓴 구도(full | bust | face)
    - `box`가 None이면 전체
    - `notice`는 한국어 안내 한 줄이고, 없으면 `""`
- **상수:** `AUTO_MIN_FACE_MM = 25`
- **bust 틀:** 폭 = 3.5w, 높이 = 1.25 × 폭, 위쪽 = y − 0.6h, 가로 중심 = x + w/2
- **face 틀:** 한 변 = 1.8 × max(w, h), 중심 = 얼굴 중심

- [ ] Step 1: 실패 테스트
  - bust·face 틀의 크기와 위치(얼굴이 가운데)
  - 왼쪽 위 가장자리 얼굴(음수 y 포함) → 틀이 이미지 안
  - 이미지보다 큰 틀 → 이미지 크기로 줄어듦
  - auto:
    - 1440px 높이 이미지에 얼굴 높이 300px, box_mm 100 → 20.8mm → bust, 알림에 "상반신"과 "21mm"
    - 얼굴 높이 400px → 27.8mm → full, 알림 없음
    - box_mm 150이면 300px 얼굴 → 31mm → full
  - 얼굴 0개 → full, 알림 없음(auto). 얼굴 2개 → full
  - `frame=bust`인데 얼굴이 없음 → full, 알림 "얼굴을 찾지 못해 전체로 그립니다"
  - `frame=full` → 얼굴이 있어도 full, 알림 없음
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 통과 → 커밋

### Task 3: 세션 입력 — 원본 해상도 구도 자르기, 얼굴 정보, 편집 초기화

**Files:**
- Modify: `mirobot_sketch/sketch_pipeline.py`(`load_color_full`, rembg 원본 크기 반환 옵션), `mirobot_sketch/stages.py`(① 원본 단계 `frame` 항목), `mirobot_sketch/session.py`
- Test: `tests/test_face_session.py`

**Interfaces:**
- Consumes: `faces.detect_faces`, `faces.choose_frame`, `faces.frame_box`
- Produces (Pipeline 입력 dict에 추가, 모두 작업 이미지 좌표):
  - `faces: list[Face]`
  - `face_crops: list[{"img": BGR, "scale": s, "origin": (ox, oy)}]`: 작업 좌표 p = 조각 좌표 / s + origin
  - `frame: {"kind", "box_orig"}`
- **`ParamSpec("frame", "구도", "choice", "auto", choices=(("auto","자동"),("full","전체"),("bust","상반신"),("face","얼굴")))`**를 ① 원본 단계에 추가한다.
- **`sp.load_color_full(path) -> BGR`:** 원본 크기이고, `load_color`와 같은 투명 합성과 8비트 변환을 한다.
- **`sp.remove_background_bgr(path, max_side=None, ...)`:** `max_side=None`이면 줄이지 않는다.
- **세션:**
  - `_inputs(rembg, frame, box_mm)`:
    - 원본(또는 rembg 원본)을 캐시하고, 원본 기준 얼굴 검출도 `(path, rembg)`마다 한 번만 한다.
    - `choose_frame`으로 틀을 정하고 자른 뒤 `resize_max_side`한다.
    - 얼굴을 작업 좌표로 옮긴다(자른 뒤 다시 검출하지 않고 변환한다).
    - 얼굴 조각을 준비한다: 얼굴 상자를 1.3×1.4 타원의 경계 상자로 넓혀 원본에서 자르고, 긴 변 500px로 맞춘다.
    - 입력 키는 `(path, rembg, box_orig 튜플 | None)`이다.
  - `run()`:
    - 새 입력 키의 틀이 직전 결과의 틀과 다르면 편집 기록·제안·되돌리기·edit_log를 비운다.
    - 알림은 "구도가 바뀌어 편집을 초기화했습니다"다. 구도 알림은 `self.frame_notice`로 결과에 넣는다.
  - `stage_summaries()["source"]`에 "· 상반신(자동)"처럼 적용된 구도를 붙인다.
  - `state()["result"]`에 `faces`(수)와 `frame`(kind)을 넣는다.

- [ ] Step 1: 실패 테스트 (`faces.detect_faces`를 가짜로 바꿔 얼굴 위치를 정함, 합성 1156×1440 이미지 파일을 임시 폴더에 저장)
  - auto에서 작은 얼굴 → 작업 이미지가 bust 틀 비율(4:5)이고 긴 변 800. 알림에 "상반신"
  - 입력의 `faces` 좌표가 작업 좌표로 옮겨졌다(틀 원점을 빼고 배율을 곱함).
  - 얼굴 조각 되돌리기: 조각 중심 좌표 / s + origin = 작업 좌표의 얼굴 중심
  - `frame=full` → 전체 이미지, faces는 여전히 있음(얼굴 세밀 처리용)
  - 편집:
    - 획을 하나 지우고 box_mm만 바꿔도 틀이 같으면(큰 얼굴, full) 편집 기록이 유지된다.
    - 작은 얼굴에서 box_mm을 100 → 200으로 바꿔 틀이 bust → full이 되면 기록이 비워지고 알림이 뜬다.
  - rembg 캐시 키: rembg 켬/끔이 서로 다른 입력을 쓴다(rembg는 가짜로 대체).
  - 얼굴 없음(가짜가 `[]`) → 결과가 지금과 같다(입력 이미지 동일).
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: 통과 + 전체 테스트(기존 세션 테스트 회귀 확인) → 커밋

### Task 4: 얼굴 세밀 단계 `face`

**Files:**
- Modify: `mirobot_sketch/stages.py`(Stage `deps`, `_run_face`, 미리보기, 설명, `stage_title` ⑩, `candidates_of`), `mirobot_sketch/sketch_pipeline.py`(타원 자르기 도우미), `mirobot_sketch/session.py`(`stage_summaries["face"]`)
- Test: `tests/test_face_stage.py`, `tests/test_stages.py`(⑩ 번호)

**Interfaces:**
- Consumes: Task 3의 입력(`faces`, `face_crops`)
- Produces:
  - `Stage.deps: tuple = ()`. `_keys`는 `p = 자기 설정 + deps 설정`으로 키를 만든다.
  - `sp.clip_to_ellipse(strokes, center, axes, inside: bool) -> list`: 타원 안(또는 밖) 부분만 남기고, 경계를 지나면 나눈다. 점 사이를 1px로 촘촘히 한 뒤 판정하고, 2점 미만 조각은 버린다.
  - `face_ellipse(face) -> (center, axes)`: 상자 중심, 반축 (0.65w, 0.7h)
  - 단계 출력: `strokes`(교체 결과), `discarded_face`(교체로 지운 원래 부분 [(점, "얼굴 세밀 처리로 교체")]), `faces_used`(수)
- **`_run_face(prev, p)`:**
  - 얼굴이 없거나 `face_detail`이 꺼져 있으면 `{**prev, "discarded_face": [], "faces_used": 0}`
  - 얼굴마다:
    1. 조각을 prep→edges→trace→dedupe→merge 러너로 돌린다. 기존 `_run_*` 함수를 조각용 입력 dict로 재사용하고, Canny 하한·상한 × `face_sensitivity`, `min_length_px`은 그대로 쓴다.
    2. 작업 좌표로 되돌린다.
    3. 밀도 제한: pen_px = `pen_mm / (box_mm / max(작업 이미지 h, w))`
       - 얼굴 획을 작업 좌표 래스터에서 `dedupe_strokes(…, dist_px=max(1, round(pen_px)))`로 겹침 제거한다.
       - 길이 < 3·pen_px인 획은 버린다. 단, 점 중 하나라도 5개 눈·코·입 점 반경 0.2·얼굴 폭 안이면 남긴다.
    4. 기존 획에서 타원 안 부분을 빼서 `discarded_face`에 넣고, 얼굴 획의 타원 안 부분을 더한다.
- **조절 항목(단계 "얼굴 세밀"):**
  - `face_detail`: bool, True
  - `face_sensitivity`: float, 0.6, 범위 0.3~1.0, 간격 0.05
  - `pen_mm`: float, 0.5, 범위 0.2~1.5, 간격 0.05
  - `deps=("box_mm",)`
- **미리보기:** `draw_strokes_colored` 위에 타원 윤곽과 5개 점을 초록(40,160,40)으로 그린다. 얼굴이 없으면 왼쪽 위에 "no face" 문구를 넣는다.

- [ ] Step 1: 실패 테스트 (합성: 흰 배경 400×400 위의 원형 "얼굴", 조각 = 같은 그림을 2배로 키운 것, Face는 직접 만듦)
  - 얼굴이 없음/끔 → strokes가 입력과 같은 객체 내용
  - 타원 안 기존 획은 사라지고, 얼굴 획으로 대체된다(타원 안 점은 모두 얼굴 획 출처).
  - 경계를 지나는 가로선(x 0~400, y=중심) → 바깥 두 조각은 남고 `discarded_face`에 안쪽 조각
  - 밀도: pen_mm 0.5 vs 1.5 → 1.5가 얼굴 획 수가 적다. box_mm 50(펜 px 커짐) vs 120 → 50이 적다.
  - 눈 점 근처의 짧은 획은 남고, 먼 곳의 짧은 획은 버려진다.
  - Pipeline 캐시: box_mm만 바꾸면 face 단계가 다시 계산된다(`run_counts["face"]` +1). `trace`는 다시 계산되지 않는다.
  - `stage_title("paper")`가 ⑩로 시작하고, `PIPELINE_IDS`에 face가 merge와 simplify 사이에 있다.
  - `candidates_of`에 `discarded_face`가 포함된다.
- [ ] Step 2: FAIL → Step 3: 구현(test_stages의 번호 문자열도 ⑩까지로 바꿈) → Step 4: 통과 + 전체 테스트 + 골든 불변 확인 → 커밋

### Task 5: 에이전트·문서·배포 확인·실제 사진 기록

**Files:** Modify `mirobot_sketch/agent/tools.py`(안내문), `README.md`, `packaging/mirobot_sketch.spec`(확인만), `LOG/2026-09-26-face-detail.md`, `LOG/README.md`, `LOG/assets/2026-09-26-face-detail/*`

- [ ] 에이전트 안내문에 추가한다.
  - source: `frame`(auto/full/bust/face)
  - face 얼굴 세밀: `face_detail`, `face_sensitivity`, `pen_mm`
  - 결과 요약의 faces·frame
- [ ] README 단계 설명(10단계, 자동 구도, 얼굴 세밀)과 `THIRD_PARTY_NOTICES.md` 링크
- [ ] exe 번들 확인: PyInstaller 빌드 없이 `collect_data_files("mirobot_sketch")` 결과에 onnx가 들어 있는지 파이썬으로 확인
- [ ] 실제 사진 확인: 세션으로 photo1~3, illust1을 처리한다.
  - 구도, 얼굴 수, 획·점 수, 예상 시간을 표로 만든다.
  - 전후 비교 그림(확대, 종이 크기)을 LOG에 넣는다.
- [ ] 전체 테스트, pyflakes → 커밋
