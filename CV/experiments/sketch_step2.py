"""
2단계: 배경 제거(rembg) + Canny
================================
1단계(sketch_step1.py)에서 배경이 그대로 엣지로 잡히는 문제를
rembg(딥러닝 배경제거, 추론만 사용)로 해결합니다.

MSER(텍스트 탐지)은 실험해봤으나 만화/일러스트 그림에서는 눈, 안경
같은 얼굴 부위를 텍스트로 오인하는 문제가 있어 제외했습니다.
텍스트가 피사체 위에 겹친 사진은 사용 전 수동으로 크롭하는 것을
권장합니다.

사용법:
    python sketch_step2.py <이미지경로>

필요한 패키지:
    pip install opencv-python matplotlib "rembg[cpu]" pillow
    (rembg 첫 실행 시 모델 파일을 자동으로 다운로드합니다 - 인터넷 필요)
"""

import sys
import io
import cv2
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from rembg import remove


def remove_background(img_path):
    """rembg로 배경을 제거하고, 흰 배경 위에 합성한 그레이스케일 이미지를 반환."""
    with open(img_path, "rb") as f:
        input_bytes = f.read()
    output_bytes = remove(input_bytes)

    # RGBA로 열어서 흰 배경 위에 합성 (투명한 부분을 흰색으로 채움)
    fg = Image.open(io.BytesIO(output_bytes)).convert("RGBA")
    white_bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, fg).convert("L")  # 그레이스케일

    return np.array(composited)


def main():
    if len(sys.argv) < 2:
        print("사용법: python sketch_step2.py <이미지경로>")
        return

    img_path = sys.argv[1]

    print("1/2: 배경 제거 중 (rembg, 첫 실행 시 모델 다운로드로 시간이 걸릴 수 있음)...")
    bg_removed = remove_background(img_path)

    print("2/2: Canny 엣지 검출...")
    blurred = cv2.GaussianBlur(bg_removed, (5, 5), 0)
    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    # 원본도 비교용으로 같이 로드
    original = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)

    fig, axes = plt.subplots(2, 2, figsize=(12, 12))

    axes[0, 0].imshow(original, cmap="gray")
    axes[0, 0].set_title("Original")
    axes[0, 0].axis("off")

    axes[0, 1].imshow(bg_removed, cmap="gray")
    axes[0, 1].set_title("After rembg (background removed)")
    axes[0, 1].axis("off")

    axes[1, 0].imshow(edges, cmap="gray")
    axes[1, 0].set_title("Canny Edges (after bg removal)")
    axes[1, 0].axis("off")

    # 비교: 필터링 없이 바로 Canny 돌린 것 (1단계 방식)
    original_blur = cv2.GaussianBlur(original, (5, 5), 0)
    original_edges = cv2.Canny(original_blur, 50, 150)
    axes[1, 1].imshow(original_edges, cmap="gray")
    axes[1, 1].set_title("Canny Edges (no filtering, for comparison)")
    axes[1, 1].axis("off")

    plt.tight_layout()
    plt.savefig("sketch_step2_result.png", dpi=150)
    print("결과가 sketch_step2_result.png 로 저장되었습니다.")
    plt.show()


if __name__ == "__main__":
    main()
