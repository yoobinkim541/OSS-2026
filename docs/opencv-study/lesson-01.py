#!/usr/bin/env python3
"""OpenCV lesson 1: inspect an image and compare grayscale, blur, and Canny."""

import argparse
from pathlib import Path

import cv2 as cv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="input photo or illustration")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("opencv_lesson1_output"),
        help="directory for saved intermediate images",
    )
    args = parser.parse_args()

    source = cv.imread(str(args.image), cv.IMREAD_COLOR)
    if source is None:
        parser.error(f"OpenCV could not read the image: {args.image}")

    height, width, channels = source.shape
    print(f"Image size (width x height): {width} x {height}")
    print(f"Channels: {channels} (OpenCV color order: BGR)")
    print(f"Data type: {source.dtype}; intensity range: {source.min()}..{source.max()}")

    gray = cv.cvtColor(source, cv.COLOR_BGR2GRAY)
    blurred = cv.GaussianBlur(gray, (5, 5), 0)
    edges_low = cv.Canny(blurred, 50, 120)
    edges_high = cv.Canny(blurred, 100, 200)

    args.out.mkdir(parents=True, exist_ok=True)
    stages = {
        "01_gray.png": gray,
        "02_blurred.png": blurred,
        "03_edges_low_50_120.png": edges_low,
        "04_edges_high_100_200.png": edges_high,
    }
    for filename, image in stages.items():
        destination = args.out / filename
        if not cv.imwrite(str(destination), image):
            raise OSError(f"Could not write output image: {destination}")
        print(f"Saved: {destination}")

    panel_height = min(height, 600)
    panel_width = max(1, round(width * panel_height / height))
    previews = [
        cv.resize(image, (panel_width, panel_height), interpolation=cv.INTER_AREA)
        for image in (gray, blurred, edges_low, edges_high)
    ]
    comparison = cv.hconcat(previews)
    comparison_path = args.out / "05_comparison_gray_blur_canny.png"
    if not cv.imwrite(str(comparison_path), comparison):
        raise OSError(f"Could not write comparison image: {comparison_path}")
    print("Comparison order: grayscale | blurred | Canny 50/120 | Canny 100/200")
    print(f"Saved: {comparison_path}")


if __name__ == "__main__":
    main()
