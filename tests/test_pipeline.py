"""CV 파이프라인과 종이 좌표 변환 테스트.

    python -m unittest discover -s tests -v
"""

import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "CV"))
import paper_mapping as pm  # noqa: E402
import sketch_pipeline as sp  # noqa: E402


def blank(h=200, w=300):
    return np.zeros((h, w), np.uint8)


class TraceStrokesTest(unittest.TestCase):
    def test_straight_line_is_traced_once(self):
        # 문제 1 재현: findContours는 1px 선을 왕복해서 길이가 두 배가 됨
        e = blank(50, 300)
        cv2.line(e, (10, 25), (290, 25), 255, 1)
        contour = sp.extract_strokes_contour(e, 5)
        self.assertGreater(sp.polyline_length(contour[0]), 500)

        strokes = sp.trace_strokes(e, 5)
        self.assertEqual(len(strokes), 1)
        self.assertAlmostEqual(sp.polyline_length(strokes[0]), 280, delta=2)

    def test_circle_becomes_one_closed_stroke(self):
        e = blank(200, 200)
        cv2.circle(e, (100, 100), 60, 255, 1)
        strokes = sp.trace_strokes(e, 5)
        self.assertEqual(len(strokes), 1)
        self.assertTrue(sp.is_closed(strokes[0]))

    def test_t_junction_splits_into_three(self):
        e = blank(200, 200)
        cv2.line(e, (20, 50), (180, 50), 255, 1)
        cv2.line(e, (100, 50), (100, 180), 255, 1)
        strokes = sp.trace_strokes(e, 5)
        self.assertEqual(len(strokes), 3)
        total = sum(sp.polyline_length(s) for s in strokes)
        self.assertAlmostEqual(total, 160 + 130, delta=6)

    def test_small_components_removed_but_letters_kept(self):
        # 문제 3 재현: 조각 단위 길이 필터가 분기점 많은 글자를 지웠음
        img = np.full((120, 400), 255, np.uint8)
        cv2.putText(img, "MIROBOT", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
        cv2.circle(img, (380, 20), 1, 0, -1)  # 점 잡음
        mask = sp.compute_dark_mask(img)
        letters = 255 - img

        def coverage(strokes):
            drawn = sp.draw_strokes_image(strokes, img.shape, thickness=5)
            return np.count_nonzero(drawn & letters) / np.count_nonzero(letters), drawn

        ceiling, _ = coverage(sp.trace_skeleton(sp.skeletonize_edges(mask)))  # 필터 없음
        got, drawn = coverage(sp.trace_strokes(mask, min_length_px=15))
        # 수정 전(조각 단위 필터)은 0.66 / 필터 없음 0.92 수준이었음
        self.assertGreater(got, 0.95 * ceiling)
        self.assertEqual(drawn[20, 380], 0)  # 잡음 점은 그리지 않음

    def test_dark_mode_gives_single_centerline_for_thick_line(self):
        # 문제 4 재현: Canny는 굵은 선 하나를 두 줄로 만듦
        img = np.full((100, 300), 255, np.uint8)
        cv2.line(img, (20, 50), (280, 50), 0, 6)
        _, canny_strokes = sp.run_pipeline(img, line_source="canny")
        _, dark_strokes = sp.run_pipeline(img, line_source="dark")
        canny_len = sum(sp.polyline_length(s) for s in canny_strokes)
        dark_len = sum(sp.polyline_length(s) for s in dark_strokes)
        self.assertGreater(canny_len, 450)
        self.assertLess(dark_len, 290)


class SimplifyAndOrderTest(unittest.TestCase):
    def test_simplify_keeps_closed_loop_closed(self):
        e = blank(200, 200)
        cv2.circle(e, (100, 100), 60, 255, 1)
        s = sp.simplify_strokes(sp.trace_strokes(e, 5), 2.0)[0]
        self.assertTrue(sp.is_closed(s))
        self.assertLess(len(s), 40)

    def test_ordering_reduces_pen_up_travel(self):
        rng = np.random.default_rng(0)
        strokes = []
        for _ in range(30):
            p = rng.uniform(0, 500, 2)
            strokes.append(np.array([p, p + rng.uniform(-20, 20, 2)]))
        before = sp.stroke_metrics(strokes, start=(250, 250))["pen_up_length"]
        after = sp.stroke_metrics(sp.order_strokes(strokes, start=(250, 250)), start=(250, 250))["pen_up_length"]
        self.assertLess(after, before * 0.6)

    def test_ordering_can_reverse_open_stroke(self):
        s = np.array([[100.0, 0.0], [0.0, 0.0]])
        ordered = sp.order_strokes([s], start=(0, 0))
        self.assertEqual(tuple(ordered[0][0]), (0.0, 0.0))


class PaperMappingTest(unittest.TestCase):
    def test_center_aspect_and_y_flip(self):
        # 200x100 px 사각형, 위쪽 변이 이미지 y=10
        strokes = [np.array([[0, 10], [200, 10], [200, 110], [0, 110], [0, 10]])]
        mm, placement = pm.pixels_to_paper(strokes, box_mm=(100, 100))
        pts = mm[0]
        self.assertAlmostEqual(placement["drawing_width_mm"], 100)
        self.assertAlmostEqual(placement["drawing_height_mm"], 50)
        self.assertAlmostEqual(pts[:, 0].min() + pts[:, 0].max(), 0)  # 가운데 정렬
        self.assertAlmostEqual(pts[:, 1].min() + pts[:, 1].max(), 0)
        self.assertAlmostEqual(pts[0][1], 25)  # 이미지 위쪽 -> 종이 위쪽(+)
        self.assertEqual(pm.check_within_paper(mm), 0)

    def test_box_larger_than_paper_rejected(self):
        with self.assertRaises(ValueError):
            pm.pixels_to_paper([np.array([[0, 0], [10, 10]])], box_mm=(300, 100))

    def test_document_roundtrip(self):
        import tempfile

        mm, placement = pm.pixels_to_paper([np.array([[0, 0], [10, 0], [10, 10]])])
        doc = pm.build_strokes_document(mm, placement)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            pm.save_strokes_json(p, doc)
            loaded, strokes = pm.load_strokes_json(p)
        self.assertEqual(loaded["kind"], "sketch_strokes")
        self.assertTrue(np.allclose(strokes[0], mm[0], atol=1e-3))
        self.assertTrue(math.isclose(abs(strokes[0][0][0]), 50, abs_tol=1e-3))


if __name__ == "__main__":
    unittest.main()
