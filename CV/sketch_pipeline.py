"""
사진 -> 로봇용 획(stroke) 추출 파이프라인
==========================================
GUI(gui_sketch.py)와 CLI(make_strokes.py)가 같이 쓰는 공용 모듈입니다.

단계:
  1. load_gray / remove_background : 이미지 읽기(+선택적 배경 제거), 크기 정규화
  2. compute_edges                 : Gaussian blur + Canny
  3. trace_strokes                 : 엣지를 1px 중심선으로 만든 뒤 픽셀 그래프를
                                     따라가며 "한 번씩만" 지나가는 획으로 분리
  4. simplify_strokes              : approxPolyDP로 점 개수 줄이기
  5. order_strokes                 : 가까운 끝점부터 이어 펜업 이동 거리 줄이기
  6. stroke_metrics                : 획 수, 점 수, 펜다운/펜업 거리

왜 findContours를 기본으로 쓰지 않는가:
  findContours는 "영역의 경계"를 돌려줍니다. 두께 1px인 Canny 선에 쓰면
  선을 따라 갔다가 반대쪽 경계를 따라 되돌아오는 폐곡선이 나오므로, 로봇이
  같은 선을 두 번 그리게 됩니다(280px 직선 -> 윤곽 길이 559px로 실측).
  비교용으로 extract_strokes_contour()를 남겨두었습니다.
"""

import io
import math

import cv2
import numpy as np

DEFAULT_MAX_SIDE = 800  # 파라미터(px 단위)가 사진 해상도에 따라 달라지지 않도록 정규화

# 8-이웃 오프셋 (dy, dx)
_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


# ---------------------------------------------------------------------------
# 1. 입력
# ---------------------------------------------------------------------------

def resize_max_side(img, max_side=DEFAULT_MAX_SIDE, upscale=True):
    """긴 변을 max_side로 맞춥니다(비율 유지). None/0이면 그대로 둡니다.

    작은 이미지도 키웁니다(upscale=True). px 단위 파라미터(최소 길이, 단순화 오차)가
    원본 해상도와 상관없이 같은 의미를 갖게 하고, 저해상도 원본의 계단 모양 선을
    매끄럽게 하기 위해서입니다 (267px 일러스트: 눈·안경이 뭉개짐 -> 800px로 키우면 보임).
    """
    if not max_side:
        return img
    h, w = img.shape[:2]
    scale = max_side / max(h, w)
    if scale == 1.0 or (scale > 1.0 and not upscale):
        return img
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=interp)


def load_gray(img_path, max_side=DEFAULT_MAX_SIDE):
    # cv2.imread는 Windows의 한글 경로를 못 읽는 경우가 있어 바이트로 읽어 디코딩
    data = np.fromfile(str(img_path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {img_path}")
    return resize_max_side(img, max_side)


def remove_background(img_path, max_side=DEFAULT_MAX_SIDE):
    """rembg로 배경을 제거하고 흰 배경 위에 합성한 회색조 이미지를 반환합니다.
    rembg는 선택 기능이라 필요할 때만 import 합니다 (첫 실행 시 모델 다운로드)."""
    from PIL import Image
    from rembg import remove

    with open(img_path, "rb") as f:
        output_bytes = remove(f.read())
    fg = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, fg).convert("L")
    return resize_max_side(np.array(composited), max_side)


# ---------------------------------------------------------------------------
# 2. 엣지
# ---------------------------------------------------------------------------

def compute_edges(gray_img, canny_low=50, canny_high=150, blur_ksize=5):
    k = int(blur_ksize)
    k = k if k % 2 == 1 else k + 1
    blurred = cv2.GaussianBlur(gray_img, (k, k), 0) if k > 1 else gray_img
    return cv2.Canny(blurred, float(canny_low), float(canny_high))


def compute_dark_mask(gray_img, blur_ksize=5, threshold=None):
    """(선화 모드) 어두운 선 영역을 흰색으로 표시한 이진 이미지.

    Canny는 두께가 있는 선의 "양쪽 경계"를 잡아 한 선을 두 줄로 만듭니다.
    선화·일러스트처럼 어두운 선이 곧 그릴 선인 입력은, 선 영역 자체를 골라낸 뒤
    골격화하면 선의 중심선 한 줄을 얻습니다.
    threshold가 None이면 Otsu로 자동 결정합니다.
    """
    k = int(blur_ksize)
    k = k if k % 2 == 1 else k + 1
    blurred = cv2.GaussianBlur(gray_img, (k, k), 0) if k > 1 else gray_img
    if threshold is None:
        _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(blurred, float(threshold), 255, cv2.THRESH_BINARY_INV)
    # 작은 점 잡음 제거
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


# ---------------------------------------------------------------------------
# 3. 획 추적
# ---------------------------------------------------------------------------

def skeletonize_edges(edges):
    """엣지 이미지를 1px 두께의 중심선(bool 배열)으로 만듭니다."""
    from skimage.morphology import skeletonize

    return skeletonize(edges > 0)


def _neighbor_list(skel):
    """골격 픽셀마다 8-이웃 골격 픽셀 목록을 만듭니다. 키는 (y, x)."""
    h, w = skel.shape
    ys, xs = np.nonzero(skel)
    nbrs = {}
    for y, x in zip(ys.tolist(), xs.tolist()):
        lst = []
        for dy, dx in _NEIGHBORS:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and skel[ny, nx]:
                lst.append((ny, nx))
        nbrs[(y, x)] = lst
    return nbrs


def trace_skeleton(skel):
    """1px 골격을 획 리스트로 바꿉니다.

    - 끝점(이웃 1개)·분기점(이웃 3개 이상)을 노드로 보고, 노드에서 노드까지를
      하나의 획으로 따라갑니다. 지나간 간선은 기록해 두 번 지나가지 않습니다.
    - 노드가 없는 순수한 고리(원 등)는 마지막에 따로 찾아 닫힌 획으로 만듭니다.

    반환: 각 획은 (N, 2) int 배열, 점 순서는 (x, y). 닫힌 획은 첫 점 == 마지막 점.
    """
    nbrs = _neighbor_list(skel)
    is_node = {p: len(n) != 2 for p, n in nbrs.items()}
    visited_edges = set()
    visited_px = set()
    strokes = []

    def edge_key(a, b):
        return (a, b) if a < b else (b, a)

    def walk(start, nxt):
        path = [start, nxt]
        visited_edges.add(edge_key(start, nxt))
        prev, cur = start, nxt
        while not is_node[cur] and cur != start:
            step = None
            for cand in nbrs[cur]:
                if cand != prev and edge_key(cur, cand) not in visited_edges:
                    step = cand
                    break
            if step is None:
                break
            visited_edges.add(edge_key(cur, step))
            path.append(step)
            prev, cur = cur, step
        return path

    # 노드에서 출발하는 획
    for p, is_n in is_node.items():
        if not is_n:
            continue
        visited_px.add(p)
        if not nbrs[p]:
            continue  # 고립 픽셀은 그릴 가치가 없음
        for q in nbrs[p]:
            if edge_key(p, q) in visited_edges:
                continue
            path = walk(p, q)
            visited_px.update(path)
            strokes.append(path)

    # 남은 고리
    for p in nbrs:
        if p in visited_px:
            continue
        unvisited = [q for q in nbrs[p] if edge_key(p, q) not in visited_edges]
        if not unvisited:
            continue
        path = walk(p, unvisited[0])
        if path[-1] != path[0]:
            # 시작점의 다른 이웃과 이어지면 고리를 닫아줌
            if path[0] in nbrs[path[-1]]:
                visited_edges.add(edge_key(path[-1], path[0]))
                path.append(path[0])
        visited_px.update(path)
        strokes.append(path)

    return [np.array([(x, y) for y, x in path], dtype=np.int32) for path in strokes]


def polyline_length(pts):
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 2:
        return 0.0
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def is_closed(pts):
    return len(pts) > 2 and tuple(pts[0]) == tuple(pts[-1])


def neighbor_count(skel):
    """골격 각 픽셀의 8-이웃 개수 (1=끝점, 2=선 중간, 3 이상=분기점)."""
    k = np.ones((3, 3), np.float32)
    k[1, 1] = 0
    return cv2.filter2D(skel.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT).astype(np.int32)


def trace_strokes(edges, min_length_px=15, spur_px=6):
    """엣지 이미지 -> 한 번씩만 지나가는 획 리스트.

    잡음 제거는 두 단계로 합니다.
      1. min_length_px: "서로 이어진 선 덩어리" 전체 픽셀 수가 이보다 작으면 제거.
         (획 조각 하나하나에 적용하면 글자처럼 분기점이 많은 선이 잘게 끊겨 사라짐)
      2. spur_px: 한쪽 끝이 허공이고 다른 끝이 분기점인 짧은 잔가지(골격화 부작용) 제거.
    분기점 사이의 1~2px짜리 연결 조각도 버립니다 (종이 위에서 0.5mm 미만).
    """
    skel = skeletonize_edges(edges)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(skel.astype(np.uint8), connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_length_px
    keep[0] = False  # 배경
    skel = keep[labels]

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
                continue
        out.append(s)
    return out


def extract_strokes_contour(edges, min_length_px=15):
    # 참고: 여기의 min_length_px는 기존 코드와 같이 "윤곽 하나의 길이" 기준
    """(비교용) 기존 방식: findContours 윤곽을 그대로 획으로 사용. 선이 두 번 그려짐."""
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for cnt in contours:
        pts = cnt.reshape(-1, 2)
        if cv2.arcLength(cnt, closed=False) >= min_length_px:
            out.append(pts.astype(np.int32))
    return out


# ---------------------------------------------------------------------------
# 4. 단순화
# ---------------------------------------------------------------------------

def simplify_strokes(strokes, epsilon_px=2.0):
    """approxPolyDP로 각 획의 점을 줄입니다. 원래 선에서 epsilon_px 이상 벗어나지 않음."""
    out = []
    for s in strokes:
        s = np.asarray(s, dtype=np.int32)
        if len(s) < 3 or epsilon_px <= 0:
            out.append(s)
            continue
        if is_closed(s):
            approx = cv2.approxPolyDP(s[:-1].reshape(-1, 1, 2), epsilon_px, closed=True).reshape(-1, 2)
            approx = np.vstack([approx, approx[:1]])
        else:
            approx = cv2.approxPolyDP(s.reshape(-1, 1, 2), epsilon_px, closed=False).reshape(-1, 2)
        out.append(approx.astype(np.int32))
    return out


# ---------------------------------------------------------------------------
# 5. 순서 정하기
# ---------------------------------------------------------------------------

def _rotate_closed(s, idx):
    """닫힌 획의 시작점을 idx 번째 점으로 바꿉니다."""
    body = s[:-1]
    body = np.roll(body, -idx, axis=0)
    return np.vstack([body, body[:1]])


def order_strokes(strokes, start=None):
    """가장 가까운 시작점부터 이어 그리는 탐욕 순서.

    - 열린 획은 앞/뒤 중 가까운 끝에서 시작하도록 뒤집을 수 있습니다.
    - 닫힌 획은 가장 가까운 꼭짓점에서 시작하도록 돌립니다.
    start: 펜의 시작 위치 (x, y). None이면 모든 획의 경계 상자 중심(=종이 중심에 대응).
    """
    remaining = [np.asarray(s, dtype=np.float64) for s in strokes if len(s) >= 2]
    if not remaining:
        return []
    if start is None:
        allp = np.vstack(remaining)
        start = (allp.min(axis=0) + allp.max(axis=0)) / 2.0
    pos = np.asarray(start, dtype=np.float64)

    # 모든 획의 "시작 후보점"을 한 배열에 모아 두고, 매 단계 numpy로 한 번에 거리를 잰다.
    # (획마다 Python 반복하던 방식은 획 2700개에 80초가 걸렸음)
    # 후보: 열린 획 = 앞 끝(mode 0) / 뒤 끝(mode 1), 닫힌 획 = 모든 꼭짓점(mode 2, j = 꼭짓점 번호)
    cand_pts, cand_owner, cand_mode, cand_j = [], [], [], []
    for i, s in enumerate(remaining):
        if is_closed(s):
            body = s[:-1]
            cand_pts.append(body)
            cand_owner.append(np.full(len(body), i))
            cand_mode.append(np.full(len(body), 2))
            cand_j.append(np.arange(len(body)))
        else:
            cand_pts.append(np.stack([s[0], s[-1]]))
            cand_owner.append(np.array([i, i]))
            cand_mode.append(np.array([0, 1]))
            cand_j.append(np.array([0, 0]))
    cand_pts = np.vstack(cand_pts)
    cand_owner = np.concatenate(cand_owner)
    cand_mode = np.concatenate(cand_mode)
    cand_j = np.concatenate(cand_j)
    alive = np.ones(len(cand_pts), dtype=bool)

    ordered = []
    for _ in range(len(remaining)):
        d = np.einsum("ij,ij->i", cand_pts - pos, cand_pts - pos)
        d[~alive] = np.inf
        k = int(np.argmin(d))
        i, mode, j = int(cand_owner[k]), int(cand_mode[k]), int(cand_j[k])
        s = remaining[i]
        if mode == 1:
            s = s[::-1]
        elif mode == 2:
            s = _rotate_closed(s, j)
        ordered.append(s)
        alive[cand_owner == i] = False
        pos = s[-1]
    return ordered


# ---------------------------------------------------------------------------
# 6. 지표
# ---------------------------------------------------------------------------

def stroke_metrics(strokes, start=None):
    """획 수, 점 수, 펜다운(그리는) 길이, 펜업(이동) 길이. 단위는 입력 좌표 단위."""
    strokes = [np.asarray(s, dtype=np.float64) for s in strokes if len(s) >= 1]
    pen_down = sum(polyline_length(s) for s in strokes)
    pen_up = 0.0
    if strokes:
        pos = strokes[0][0] if start is None else np.asarray(start, dtype=np.float64)
        for s in strokes:
            pen_up += float(np.linalg.norm(s[0] - pos))
            pos = s[-1]
        if start is not None:
            pen_up += float(np.linalg.norm(pos - np.asarray(start, dtype=np.float64)))
    return {
        "stroke_count": len(strokes),
        "point_count": int(sum(len(s) for s in strokes)),
        "pen_down_length": round(pen_down, 2),
        "pen_up_length": round(pen_up, 2),
    }


# ---------------------------------------------------------------------------
# 전체 실행 + 미리보기
# ---------------------------------------------------------------------------

def run_pipeline(gray_img, canny_low=50, canny_high=150, blur_ksize=5,
                 min_length_px=15, epsilon_px=2.0, method="skeleton", line_source="canny",
                 median_ksize=0):
    """회색조 이미지 -> (선 후보 이미지, 정렬된 획 리스트).

    line_source:  "canny"(사진 윤곽) | "dark"(선화: 어두운 선의 중심선)
    method:       "skeleton"(한 번씩만 지나감) | "contour"(비교용 기존 방식)
    median_ksize: 0이 아니면 먼저 미디언 블러. 만화 스크린톤(망점)처럼 작은 무늬를
                  지우고 선의 경계는 남긴다 (만화 1장: 2726획 -> 175획, 7px 기준).
    """
    if median_ksize and median_ksize > 1:
        k = int(median_ksize)
        gray_img = cv2.medianBlur(gray_img, k if k % 2 == 1 else k + 1)
    if line_source == "dark":
        edges = compute_dark_mask(gray_img, blur_ksize)
    else:
        edges = compute_edges(gray_img, canny_low, canny_high, blur_ksize)
    if method == "contour":
        raw = extract_strokes_contour(edges, min_length_px)
    else:
        raw = trace_strokes(edges, min_length_px)
    strokes = order_strokes(simplify_strokes(raw, epsilon_px))
    return edges, strokes


def draw_strokes_image(strokes, shape, thickness=1):
    canvas = np.zeros(shape[:2], dtype=np.uint8)
    for s in strokes:
        pts = np.round(np.asarray(s)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(canvas, [pts], isClosed=False, color=255, thickness=thickness)
    return canvas


def draw_order_preview(strokes, shape):
    """그리는 순서 확인용 컬러 미리보기: 획은 순서대로 파랑->빨강, 펜업 이동은 회색 점선."""
    h, w = shape[:2]
    canvas = np.full((h, w, 3), 255, dtype=np.uint8)
    n = max(len(strokes), 1)
    prev_end = None
    for i, s in enumerate(strokes):
        pts = np.round(np.asarray(s)).astype(np.int32)
        if prev_end is not None:
            _dashed_line(canvas, tuple(prev_end), tuple(pts[0]), (180, 180, 180))
        t = i / max(n - 1, 1)
        color = (int(255 * (1 - t)), 0, int(255 * t))  # BGR
        cv2.polylines(canvas, [pts.reshape(-1, 1, 2)], False, color, 1, cv2.LINE_AA)
        prev_end = pts[-1]
    return canvas


def _dashed_line(img, p0, p1, color, dash=6):
    length = math.dist(p0, p1)
    if length < 1:
        return
    steps = int(length // dash)
    for k in range(0, steps, 2):
        a = (int(p0[0] + (p1[0] - p0[0]) * k / steps), int(p0[1] + (p1[1] - p0[1]) * k / steps))
        b = (int(p0[0] + (p1[0] - p0[0]) * (k + 1) / steps), int(p0[1] + (p1[1] - p0[1]) * (k + 1) / steps))
        cv2.line(img, a, b, color, 1)
