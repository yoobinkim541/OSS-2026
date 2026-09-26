"""
앱 아이콘 만들기 — 원본 그림(assets/app_icon_source.webp)에서 둥근 사각형 아이콘만 잘라냄
=========================================================================================
원본은 흰 배경 위에 둥근 사각형 아이콘과 그 둘레의 옅은 번짐이 있는 1024px 그림입니다.
둥근 사각형 바깥(흰 배경·번짐)을 투명하게 하고, 사각형 크기로 잘라 여러 크기로 저장합니다.

    python assets/make_icon.py

출력: assets/app_icon.png (1024), assets/app_icon_256.png, assets/app_icon.ico
      + mirobot_sketch/data/ 에 앱이 쓰는 app_icon_256.png, app_icon.ico 복사
"""

import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "mirobot_sketch" / "data"
SOURCE = HERE / "app_icon_source.webp"
WHITE_DIST = 150      # 흰색에서 이만큼 먼(색이 진한) 픽셀의 범위 = 둥근 사각형
RADIUS_RATIO = 0.203  # 모서리 반지름 / 한 변 (원본 대각선 측정: 768px 사각형에서 약 156px)
INSET = 1.5           # 가장자리 흰 테두리가 비치지 않게 안쪽으로 조금
SS = 4                # 가장자리 매끄럽게 (4배로 그린 뒤 줄임)


def tile_box(rgb):
    """흰 배경 위 둥근 사각형의 테두리 상자 (x0, y0, x1, y1), 정사각형으로 맞춤."""
    a = np.asarray(rgb, dtype=np.float32)
    dist = np.sqrt(((255 - a) ** 2).sum(axis=2))
    ys, xs = np.nonzero(dist > WHITE_DIST)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))


def rounded_mask(side):
    big = Image.new("L", (side * SS, side * SS), 0)
    r = RADIUS_RATIO * side * SS
    ImageDraw.Draw(big).rounded_rectangle([INSET * SS, INSET * SS, (side - INSET) * SS, (side - INSET) * SS],
                                          radius=r, fill=255)
    return big.resize((side, side), Image.LANCZOS)


def make():
    rgb = Image.open(SOURCE).convert("RGB")
    box = tile_box(rgb)
    tile = rgb.crop(box).convert("RGBA")
    tile.putalpha(rounded_mask(tile.width))
    out = tile.resize((1024, 1024), Image.LANCZOS)
    out.save(HERE / "app_icon.png")
    out.resize((256, 256), Image.LANCZOS).save(HERE / "app_icon_256.png")
    out.save(HERE / "app_icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for name in ("app_icon_256.png", "app_icon.ico"):
        shutil.copy2(HERE / name, DATA / name)
    print("잘라낸 영역:", box, "→ saved:", HERE / "app_icon.png", HERE / "app_icon.ico", "(+ mirobot_sketch/data)")
    return box


if __name__ == "__main__":
    make()
