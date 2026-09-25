"""
사진 한 장 -> 종이 좌표 획 JSON + 미리보기 이미지 (명령줄 버전)
==============================================================
GUI 없이 같은 파라미터로 결과를 재현할 때 사용합니다. 사용한 파라미터는
출력 JSON의 "source" 항목에 함께 저장됩니다.

사용법:
    python CV/make_strokes.py photo.jpg
    python CV/make_strokes.py photo.jpg --detail low --out out/photo_low
    python CV/make_strokes.py photo.jpg --rembg --box 80 80 --method contour

출력:
    <out>.json          : robot/draw_executor.py 가 읽는 획 데이터 (mm)
    <out>_preview.png   : 입력 / 엣지 / 획 / 그리는 순서 비교 이미지
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_mapping as pm  # noqa: E402
import sketch_pipeline as sp  # noqa: E402

# 상세도 프리셋: (canny_low, canny_high, min_length_px, epsilon_px)
DETAIL_PRESETS = {
    "low": (80, 200, 40, 3.0),
    "medium": (50, 150, 15, 2.0),
    "high": (30, 100, 8, 1.0),
}


def estimate_time_s(metrics_mm, draw_feed, travel_feed):
    """이론상 최소 시간(가감속·명령 처리 지연 제외). 실측과 비교해 보정할 것."""
    return (metrics_mm["pen_down_length"] / draw_feed
            + metrics_mm["pen_up_length"] / travel_feed) * 60.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--out", type=Path, help="출력 경로(확장자 제외). 기본: 입력 파일 이름_strokes")
    ap.add_argument("--detail", choices=DETAIL_PRESETS, default="medium")
    ap.add_argument("--canny", type=float, nargs=2, metavar=("LOW", "HIGH"))
    ap.add_argument("--min-length", type=float, help="이보다 짧은 획 제거 (px)")
    ap.add_argument("--epsilon", type=float, help="단순화 허용 오차 (px)")
    ap.add_argument("--blur", type=int, default=5)
    ap.add_argument("--max-side", type=int, default=sp.DEFAULT_MAX_SIDE)
    ap.add_argument("--method", choices=["skeleton", "contour"], default="skeleton",
                    help="skeleton: 선을 한 번씩만 지나감(기본) / contour: 비교용 기존 방식")
    ap.add_argument("--lines", choices=["canny", "dark"], default="canny",
                    help="canny: 사진 윤곽(기본) / dark: 선화의 어두운 선 중심선")
    ap.add_argument("--median", type=int, default=0,
                    help="미디언 블러 크기(px). 만화 스크린톤 제거에 7 정도 (기본 0 = 사용 안 함)")
    ap.add_argument("--rembg", action="store_true", help="배경 제거 사용 (선택, 느림)")
    ap.add_argument("--box", type=float, nargs=2, default=pm.DEFAULT_BOX_MM, metavar=("W", "H"),
                    help="그리기 상자 크기 mm (기본 100 100)")
    ap.add_argument("--draw-feed", type=float, default=300.0, help="시간 추정용 펜다운 속도 mm/min")
    ap.add_argument("--travel-feed", type=float, default=600.0, help="시간 추정용 펜업 속도 mm/min")
    args = ap.parse_args()

    low, high, min_len, eps = DETAIL_PRESETS[args.detail]
    if args.canny:
        low, high = args.canny
    if args.min_length is not None:
        min_len = args.min_length
    if args.epsilon is not None:
        eps = args.epsilon

    gray = (sp.remove_background(args.image, args.max_side) if args.rembg
            else sp.load_gray(args.image, args.max_side))
    edges, strokes_px = sp.run_pipeline(gray, low, high, args.blur, min_len, eps, args.method, args.lines,
                                        args.median)
    if not strokes_px:
        print("획이 하나도 없습니다. --detail high 또는 Canny 임계값을 낮춰보세요.")
        return 1

    strokes_mm, placement = pm.pixels_to_paper(strokes_px, box_mm=tuple(args.box))
    metrics = sp.stroke_metrics(strokes_mm, start=(0.0, 0.0))  # 펜은 종이 중심에서 출발/복귀
    metrics["estimated_min_time_s"] = round(estimate_time_s(metrics, args.draw_feed, args.travel_feed), 1)
    metrics["time_estimate_note"] = "pen_down/draw_feed + pen_up/travel_feed only; excludes approach/retract and command latency"

    source = {
        "image": str(args.image),
        "image_size_px": [int(gray.shape[1]), int(gray.shape[0])],
        "params": {
            "detail": args.detail, "canny_low": low, "canny_high": high, "blur_ksize": args.blur,
            "min_length_px": min_len, "epsilon_px": eps, "max_side": args.max_side,
            "method": args.method, "line_source": args.lines, "median_ksize": args.median, "rembg": args.rembg,
            "draw_feed_mm_per_min": args.draw_feed, "travel_feed_mm_per_min": args.travel_feed,
        },
    }
    doc = pm.build_strokes_document(strokes_mm, placement, metrics, source)

    out = args.out or args.image.with_name(args.image.stem + "_strokes")
    out.parent.mkdir(parents=True, exist_ok=True)
    pm.save_strokes_json(out.with_suffix(".json"), doc)

    preview = np.hstack([
        cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR),
        cv2.cvtColor(255 - edges, cv2.COLOR_GRAY2BGR),
        cv2.cvtColor(255 - sp.draw_strokes_image(strokes_px, gray.shape), cv2.COLOR_GRAY2BGR),
        sp.draw_order_preview(strokes_px, gray.shape),
    ])
    preview_path = out.with_name(out.name + "_preview.png")
    cv2.imencode(".png", preview)[1].tofile(str(preview_path))

    print(f"획 {metrics['stroke_count']}개, 점 {metrics['point_count']}개")
    print(f"그림 크기 {placement['drawing_width_mm']} x {placement['drawing_height_mm']} mm")
    print(f"펜다운 {metrics['pen_down_length']} mm, 펜업 이동 {metrics['pen_up_length']} mm")
    print(f"이론상 최소 시간 {metrics['estimated_min_time_s']} s (실제는 더 걸림)")
    print(f"저장: {out.with_suffix('.json')}")
    print(f"미리보기: {preview_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
