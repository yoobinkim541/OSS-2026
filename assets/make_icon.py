"""
앱 아이콘 생성 스크립트 (외부 이미지 없이 코드로 그림)
=====================================================
로봇 팔이 펜으로 종이에 스케치를 그리는 모습. 1024px로 4배 크게 그린 뒤 줄여
가장자리를 매끄럽게 만듭니다.

    python assets/make_icon.py

출력: assets/app_icon.png (1024), assets/app_icon_256.png, assets/app_icon.ico
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
S = 4                 # 슈퍼샘플링 배율
N = 1024 * S

BG_TOP = (32, 64, 104)
BG_BOTTOM = (14, 28, 48)
PAPER = (250, 248, 242)
INK = (34, 40, 52)
ARM = (245, 165, 36)
ARM_DARK = (196, 120, 20)
JOINT = (255, 236, 200)
PEN = (90, 170, 255)


def p(x, y):
    return (x * S, y * S)


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return m


def thick_line(d, pts, width, color):
    """굵은 선. 꺾이는 곳마다 둥근 점을 찍어 이음새의 가시 자국을 없앱니다."""
    d.line([p(*q) for q in pts], fill=color, width=width * S)
    r = width * S / 2
    for x, y in pts:
        d.ellipse((x * S - r, y * S - r, x * S + r, y * S + r), fill=color)


def main():
    # 배경: 세로 그라데이션 + 둥근 모서리
    grad = np.linspace(0, 1, N)[:, None]
    bg = (np.array(BG_TOP) * (1 - grad) + np.array(BG_BOTTOM) * grad)[:, None, :].repeat(N, axis=1)
    img = Image.fromarray(bg.astype(np.uint8), "RGB").convert("RGBA")

    # 종이 그림자 + 종이 (벽에 붙은 A4 가로)
    paper = (300, 160, 924, 640)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((*p(paper[0] + 14, paper[1] + 24), *p(paper[2] + 14, paper[3] + 24)),
                                             radius=30 * S, fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(20 * S)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((*p(paper[0], paper[1]), *p(paper[2], paper[3])), radius=30 * S, fill=PAPER)

    # 종이 위 스케치: 그리는 중인 하트 (프로젝트에서 처음 그린 도형)
    t = np.linspace(0, 2 * np.pi, 400)
    hx = 16 * np.sin(t) ** 3
    hy = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    cx, cy, k = 640, 380, 11.5
    heart = [(cx + k * x, cy - k * y) for x, y in zip(hx, hy)]
    drawn = heart[: int(len(heart) * 0.80)]          # 80%까지 그린 상태
    thick_line(d, drawn, 16, INK)
    thick_line(d, heart[int(len(heart) * 0.80):], 6, (200, 200, 205))  # 남은 경로(연한 점선 느낌)
    tip = drawn[-1]

    # 로봇 팔: 받침 -> 어깨 -> 팔꿈치 -> 손목 -> 펜 끝
    base, shoulder = (230, 890), (230, 720)
    wrist = (tip[0] - 120, tip[1] + 150)
    elbow = (250, 480)
    d.rounded_rectangle((*p(130, 858), *p(330, 930)), radius=28 * S, fill=ARM_DARK)
    thick_line(d, [base, shoulder], 84, ARM_DARK)
    thick_line(d, [shoulder, elbow], 66, ARM)
    thick_line(d, [elbow, wrist], 54, ARM)
    thick_line(d, [wrist, tip], 24, PEN)        # 펜홀더 + 펜
    for (x, y), r in ((shoulder, 44), (elbow, 36), (wrist, 28)):
        d.ellipse((*p(x - r, y - r), *p(x + r, y + r)), fill=JOINT, outline=ARM_DARK, width=9 * S)
    d.ellipse((*p(tip[0] - 15, tip[1] - 15), *p(tip[0] + 15, tip[1] + 15)), fill=INK)

    img.putalpha(Image.eval(rounded_mask(N, 220 * S), lambda v: v))
    out = img.resize((1024, 1024), Image.LANCZOS)
    out.save(HERE / "app_icon.png")
    out.resize((256, 256), Image.LANCZOS).save(HERE / "app_icon_256.png")
    out.save(HERE / "app_icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("saved:", HERE / "app_icon.png", HERE / "app_icon.ico")


if __name__ == "__main__":
    main()
