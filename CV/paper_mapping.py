"""
픽셀 획 -> 종이 좌표(mm) 변환과 JSON 내보내기
============================================
좌표 약속 (이 파일이 만드는 JSON의 기준):
  - 원점: 종이 중심
  - x_mm: 종이를 정면에서 봤을 때 오른쪽이 +
  - y_mm: 종이를 정면에서 봤을 때 위쪽이 +
  이미지 좌표는 y가 아래로 커지므로 변환할 때 부호를 뒤집습니다.

로봇 축(Y/Z)으로의 변환은 여기서 하지 않고 robot/draw_executor.py가
robot/drawing_config.json의 부호·중심 설정으로 처리합니다. CV 결과는
로봇 설정이 바뀌어도 다시 만들 필요가 없습니다.

배치 규칙 (설계 문서 5.2):
  - 획 전체의 경계 상자 중심을 종이 중심에 맞춘다.
  - 가로세로 비율을 유지하며 그리기 상자(box_width_mm x box_height_mm) 안에 넣는다.
  - 그리기 상자는 종이 안전 여백 안에 있어야 한다.
"""

import json
from datetime import datetime

import numpy as np

A4_LANDSCAPE_MM = (297.0, 210.0)
DEFAULT_MARGIN_MM = 20.0
# 실물에서 끝까지 실행된 가장 큰 도형이 100mm 원이라 기본 그리기 크기를 100mm로 둡니다.
# 더 크게 그리려면 도달 범위(Soft limit)를 먼저 확인하세요.
DEFAULT_BOX_MM = (100.0, 100.0)

SCHEMA_VERSION = 1


def strokes_bbox(strokes):
    allp = np.vstack([np.asarray(s, dtype=np.float64) for s in strokes])
    return allp.min(axis=0), allp.max(axis=0)


def pixels_to_paper(strokes_px, box_mm=DEFAULT_BOX_MM, paper_mm=A4_LANDSCAPE_MM,
                    margin_mm=DEFAULT_MARGIN_MM):
    """픽셀 획들을 종이 중심 기준 mm 획들로 변환합니다.

    반환: (strokes_mm, placement) — placement에는 배율, 실제 그림 크기 등이 들어갑니다.
    """
    strokes_px = [np.asarray(s, dtype=np.float64) for s in strokes_px if len(s) >= 2]
    if not strokes_px:
        raise ValueError("변환할 획이 없습니다.")

    box_w, box_h = box_mm
    safe_w = paper_mm[0] - 2 * margin_mm
    safe_h = paper_mm[1] - 2 * margin_mm
    if box_w > safe_w or box_h > safe_h:
        raise ValueError(
            f"그리기 상자 {box_w}x{box_h}mm가 종이 안전 영역 {safe_w}x{safe_h}mm보다 큽니다."
        )

    lo, hi = strokes_bbox(strokes_px)
    size = np.maximum(hi - lo, 1e-9)
    scale = min(box_w / size[0], box_h / size[1])  # mm per px, 비율 유지
    center = (lo + hi) / 2.0

    strokes_mm = []
    for s in strokes_px:
        x = (s[:, 0] - center[0]) * scale
        y = -(s[:, 1] - center[1]) * scale  # 이미지 y(아래 +) -> 종이 y(위 +)
        strokes_mm.append(np.column_stack([x, y]))

    placement = {
        "paper_width_mm": paper_mm[0],
        "paper_height_mm": paper_mm[1],
        "margin_mm": margin_mm,
        "box_width_mm": box_w,
        "box_height_mm": box_h,
        "scale_mm_per_px": round(float(scale), 6),
        "drawing_width_mm": round(float(size[0] * scale), 3),
        "drawing_height_mm": round(float(size[1] * scale), 3),
        "alignment": "bounding_box_center_to_paper_center",
    }
    return strokes_mm, placement


def check_within_paper(strokes_mm, paper_mm=A4_LANDSCAPE_MM, margin_mm=DEFAULT_MARGIN_MM):
    """모든 점이 종이 안전 영역 안에 있는지 확인합니다. 벗어난 점 수를 반환합니다."""
    half_w = paper_mm[0] / 2 - margin_mm
    half_h = paper_mm[1] / 2 - margin_mm
    bad = 0
    for s in strokes_mm:
        s = np.asarray(s)
        bad += int(np.sum((np.abs(s[:, 0]) > half_w + 1e-6) | (np.abs(s[:, 1]) > half_h + 1e-6)))
    return bad


def build_strokes_document(strokes_mm, placement, metrics_mm=None, source=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "sketch_strokes",
        "created_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "units": "mm",
        "paper": {"size": "A4", "orientation": "landscape"},
        "coordinate_frame": {
            "origin": "paper_center",
            "x_axis": "paper_right_positive (viewed from the front of the paper)",
            "y_axis": "paper_up_positive",
            "robot_mapping": "done by robot/draw_executor.py using robot/drawing_config.json",
        },
        "placement": placement,
        "source": source or {},
        "metrics": metrics_mm or {},
        "strokes": [
            {
                "closed": bool(len(s) > 2 and np.allclose(s[0], s[-1])),
                "points_xy_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in s],
            }
            for s in strokes_mm
        ],
    }


def save_strokes_json(path, document):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=1)


def load_strokes_json(path):
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("kind") != "sketch_strokes":
        raise ValueError(f"sketch_strokes 형식이 아닙니다: {path}")
    strokes = [np.asarray(s["points_xy_mm"], dtype=np.float64) for s in doc["strokes"]]
    return doc, strokes
