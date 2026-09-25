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
