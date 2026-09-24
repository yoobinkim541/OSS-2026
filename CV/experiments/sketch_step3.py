"""
3단계: 윤곽선 추출 + 경로 단순화 + 작은 획 필터링
====================================================
2단계에서 만든 Canny 엣지 이미지(흰 선 픽셀들)를 로봇이 실제로
그릴 수 있는 "좌표 시퀀스들의 목록(획 리스트)"으로 변환합니다.

  1. findContours로 엣지를 이어진 선(윤곽선)들로 묶음
  2. approxPolyDP로 각 윤곽선의 점 개수를 줄여 직선 구간으로 근사
  3. 너무 짧은/작은 윤곽선은 노이즈로 간주하고 제거
  4. 필터링 전/후의 획 개수와 총 점 개수를 비교해서 출력

사용법:
    python sketch_step3.py <이미지경로>

필요한 패키지: pip install opencv-python matplotlib "rembg[cpu]" pillow
"""

import sys
import io
import cv2
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from rembg import remove


def remove_background(img_path):
    with open(img_path, "rb") as f:
        input_bytes = f.read()
    output_bytes = remove(input_bytes)
    fg = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, fg).convert("L")
    return np.array(composited)


def extract_strokes(edges, min_contour_length=15, epsilon_px=2.0):
    """Canny 엣지 이미지에서 획(stroke) 리스트를 추출합니다.

    min_contour_length: 이 길이(픽셀 둘레) 미만인 윤곽선은 노이즈로 간주해 버림.
                         숫자를 키울수록 더 많은 잔선이 제거됨.
    epsilon_px:          approxPolyDP의 근사 정밀도를 "고정 픽셀 값"으로 지정.
                         윤곽선 길이에 비례하지 않으므로, 긴 선이 과도하게
                         직선화되는 문제가 없음. 값이 클수록 더 단순해지되,
                         원래 곡선에서 벗어나는 최대 거리가 이 값으로 제한됨.

    반환값: (전체 윤곽선 리스트, 필터링+단순화된 획 리스트)
    """
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    all_contours = contours
    filtered_strokes = []

    for cnt in contours:
        length = cv2.arcLength(cnt, closed=False)
        if length < min_contour_length:
            continue  # 너무 짧은 획은 노이즈로 간주하고 버림

        # 길이에 비례하지 않는 고정 오차값 사용 (긴 선의 과도한 왜곡 방지)
        approx = cv2.approxPolyDP(cnt, epsilon_px, closed=False)
        filtered_strokes.append(approx)

    return all_contours, filtered_strokes


def count_points(strokes):
    return sum(len(s) for s in strokes)


def draw_strokes(strokes, shape):
    """획 리스트를 이미지로 그려서 시각화용으로 반환."""
    canvas = np.zeros(shape, dtype=np.uint8)
    for stroke in strokes:
        pts = stroke.reshape(-1, 2)
        for i in range(len(pts) - 1):
            cv2.line(canvas, tuple(pts[i]), tuple(pts[i + 1]), 255, 1)
    return canvas


def main():
    if len(sys.argv) < 2:
        print("사용법: python sketch_step3.py <이미지경로>")
        return

    img_path = sys.argv[1]

    print("1/3: 배경 제거 중...")
    bg_removed = remove_background(img_path)

    print("2/3: Canny 엣지 검출...")
    blurred = cv2.GaussianBlur(bg_removed, (5, 5), 0)
    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    print("3/3: 윤곽선 추출 및 단순화...")
    all_contours, filtered_strokes = extract_strokes(
        edges, min_contour_length=15, epsilon_px=2.0
    )

    total_points_before = count_points(all_contours)
    total_points_after = count_points(filtered_strokes)

    print(f"\n=== 결과 요약 ===")
    print(f"필터링 전 윤곽선 개수: {len(all_contours)}")
    print(f"필터링 후 획(stroke) 개수: {len(filtered_strokes)}")
    print(f"필터링 전 총 점 개수: {total_points_before}")
    print(f"필터링+단순화 후 총 점 개수: {total_points_after}")
    print(f"점 개수 감소율: {(1 - total_points_after / max(total_points_before, 1)) * 100:.1f}%")

    # 시각화
    simplified_img = draw_strokes(filtered_strokes, edges.shape)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))

    axes[0].imshow(edges, cmap="gray")
    axes[0].set_title(f"Canny Edges (raw pixels)")
    axes[0].axis("off")

    all_contours_img = np.zeros(edges.shape, dtype=np.uint8)
    cv2.drawContours(all_contours_img, all_contours, -1, 255, 1)
    axes[1].imshow(all_contours_img, cmap="gray")
    axes[1].set_title(f"All Contours ({len(all_contours)} strokes)")
    axes[1].axis("off")

    axes[2].imshow(simplified_img, cmap="gray")
    axes[2].set_title(
        f"Filtered+Simplified ({len(filtered_strokes)} strokes, "
        f"{total_points_after} pts)"
    )
    axes[2].axis("off")

    plt.tight_layout()
    plt.savefig("sketch_step3_result.png", dpi=150)
    print("\n결과가 sketch_step3_result.png 로 저장되었습니다.")
    plt.show()


if __name__ == "__main__":
    main()
