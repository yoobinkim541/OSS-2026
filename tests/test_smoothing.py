"""획 스무딩: 픽셀 계단·지그재그를 없애고 끝점과 닫힌 모양은 지킴."""

import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import sketch_pipeline as sp  # noqa: E402
from mirobot_sketch import stages  # noqa: E402


def jittered_arc(seed=0):
    """반지름 150px 원호에 ±1.2px 흔들림 — Canny 선이 흔들리는 모양을 흉내 냄."""
    rng = np.random.default_rng(seed)
    th = np.radians(np.linspace(5, 85, 60))
    r = 150 + rng.uniform(-1.2, 1.2, 60)
    pts = np.stack([20 + r * np.cos(th), 20 + r * np.sin(th)], 1).round().astype(np.int32)
    img = np.zeros((200, 200), np.uint8)
    cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, 255, 1)
    return sp.trace_strokes(img, 5)


def zigzag(s):
    """(꺾는 방향이 바뀐 횟수, 가장 큰 꺾임 각도). 매끄러운 원호는 한쪽으로만 꺾임."""
    d = np.diff(np.asarray(s, float), axis=0)
    a = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
    t = (np.diff(a) + 180) % 360 - 180
    t = t[np.abs(t) > 2]
    flips = int(np.sum(np.sign(t[1:]) != np.sign(t[:-1]))) if len(t) > 1 else 0
    return flips, float(np.abs(t).max()) if len(t) else 0.0


def finish(strokes, sigma=2.0, eps=1.0, rounds=1):
    return sp.round_corners(sp.simplify_strokes(sp.smooth_strokes(strokes, sigma), eps), rounds)


class SmoothingTest(unittest.TestCase):
    def test_jittered_arc_becomes_smooth(self):
        raw = jittered_arc()
        before = zigzag(sp.simplify_strokes(raw, 1.0)[0])
        self.assertGreater(before[0], 10)                  # 지금 방식은 지그재그 (기준 확인)
        after = finish(raw)[0]
        flips, worst = zigzag(after)
        self.assertLessEqual(flips, 2)
        self.assertLess(worst, 25)

    def test_open_stroke_keeps_endpoints(self):
        raw = jittered_arc()
        out = finish(raw)[0]
        np.testing.assert_allclose(out[0], raw[0][0])
        np.testing.assert_allclose(out[-1], raw[0][-1])

    def test_closed_stroke_stays_closed_and_round(self):
        img = np.zeros((200, 200), np.uint8)
        cv2.circle(img, (100, 100), 60, 255, 1)
        raw = sp.trace_strokes(img, 5)
        self.assertTrue(sp.is_closed(raw[0]))
        out = finish(raw)[0]
        self.assertTrue(np.allclose(out[0], out[-1]))
        r = np.hypot(out[:, 0] - 100, out[:, 1] - 100)
        self.assertLess(r.max() - r.min(), 2.5)            # 여전히 원 (크게 줄어들지 않음)
        self.assertGreater(r.mean(), 58)

    def test_zero_settings_match_old_simplify(self):
        raw = jittered_arc()
        old = sp.simplify_strokes(raw, 1.0)
        new = finish(raw, sigma=0, rounds=0)
        self.assertEqual(len(old), len(new))
        for a, b in zip(old, new):
            np.testing.assert_array_equal(a, b)

    def test_short_strokes_survive(self):
        short = [np.array([[0, 0], [3, 1]], np.int32), np.array([[5, 5], [6, 6], [7, 6]], np.int32)]
        out = finish(short)
        self.assertEqual(len(out), 2)
        for a, b in zip(short, out):
            np.testing.assert_allclose(b[0], a[0])
            np.testing.assert_allclose(b[-1], a[-1])

    def test_rounding_keeps_sharp_tips(self):
        # 머리카락 끝(V자)과 되돌아가는 선: 둥글리기가 뾰족한 끝을 잘라 선을 짧게 만들면 안 됨
        v = np.array([[0, 0], [100, 40], [0, 80]], float)
        back = np.array([[20, 50], [280, 50], [20, 50]], float)       # 닫힌 고리가 납작해진 모양
        for s in (v, back):
            for n in (1, 3):
                out = sp.round_corners([s], n)[0]
                tip_before = np.max(np.hypot(*(s - s[0]).T))
                tip_after = np.max(np.hypot(*(out - s[0]).T))
                self.assertGreater(tip_after, tip_before - 1.5, (s.tolist(), n))

    def test_rounding_still_rounds_gentle_corners(self):
        sq = np.array([[0, 0], [40, 0], [80, 10]], float)             # 14° 꺾임
        out = sp.round_corners([sq], 1)[0]
        self.assertEqual(len(out), 4)                                 # 꼭짓점 하나가 두 점으로
        self.assertFalse(any(np.allclose(p, [40, 0]) for p in out))

    def test_stage_has_smoothing_params(self):
        p = stages.default_params()
        self.assertEqual(p["smooth_sigma_px"], 2.0)
        self.assertEqual(p["round_iters"], 1)
        self.assertEqual(stages.STAGE_BY_ID["simplify"].label, "스무딩·단순화")
        raw = jittered_arc()
        out = stages._run_simplify({"strokes": raw}, p)["strokes"]
        self.assertLessEqual(zigzag(out[0])[0], 2)


if __name__ == "__main__":
    unittest.main()
