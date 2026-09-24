"""
1단계: 사진 -> 스케치(엣지) 변환
================================
가장 기본적인 Canny 엣지 검출부터 시작합니다.
결과 이미지를 눈으로 보면서 파라미터를 조정해나갈 거예요.

사용법:
    python sketch_step1.py <이미지경로>
    예: python sketch_step1.py photo.jpg

필요한 패키지: pip install opencv-python matplotlib
"""

import sys
import cv2
import matplotlib.pyplot as plt


def main():
    if len(sys.argv) < 2:
        print("사용법: python sketch_step1.py <이미지경로>")
        return

    img_path = sys.argv[1]

    # 1. 이미지 읽기 (그레이스케일로)
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"이미지를 읽을 수 없습니다: {img_path}")
        return

    print(f"이미지 크기: {img.shape}")

    # 2. 노이즈 줄이기 (약한 블러)
    blurred = cv2.GaussianBlur(img, (5, 5), 0)

    # 3. Canny 엣지 검출 (일단 고정 임계값으로 시작)
    #    threshold1, threshold2 값을 나중에 조정해볼 예정
    edges = cv2.Canny(blurred, threshold1=50, threshold2=150)

    # 4. 결과를 나란히 보여주기
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    axes[0].imshow(img, cmap="gray")
    axes[0].set_title("Original (Grayscale)")
    axes[0].axis("off")

    axes[1].imshow(blurred, cmap="gray")
    axes[1].set_title("After Blur")
    axes[1].axis("off")

    axes[2].imshow(edges, cmap="gray")
    axes[2].set_title("Canny Edges (50, 150)")
    axes[2].axis("off")

    plt.tight_layout()
    plt.savefig("sketch_step1_result.png", dpi=150)
    print("결과가 sketch_step1_result.png 로 저장되었습니다.")
    plt.show()


if __name__ == "__main__":
    main()
