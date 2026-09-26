"""얼굴 검출(YuNet)과 구도 계산 (검출기는 가짜로 대체 — 실제 사진이 없어도 동작)."""

import hashlib
import sys
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mirobot_sketch import faces  # noqa: E402

INPUT = ROOT / "input"


def raw(x, y, w, h, score, lm=None):
    """YuNet 한 줄: x y w h, 눈·코·입 5점(10개), 신뢰도."""
    lm = lm if lm is not None else [x + w * f for f in (0.3, 0.7, 0.5, 0.35, 0.65)] + \
        [y + h * f for f in (0.4, 0.4, 0.6, 0.8, 0.8)]
    pts = np.array([lm[0], lm[5], lm[1], lm[6], lm[2], lm[7], lm[3], lm[8], lm[4], lm[9]])
    return np.concatenate([[x, y, w, h], pts, [score]]).astype(np.float32)


def fake(rows):
    return lambda img: np.array(rows, np.float32) if rows else None


class ModelTest(unittest.TestCase):
    def test_model_file_is_bundled(self):
        data = faces.MODEL_PATH.read_bytes()
        self.assertEqual(len(data), 232589)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4")

    def test_real_model_loads_and_blank_has_no_face(self):
        if not hasattr(cv2, "FaceDetectorYN"):
            self.skipTest("OpenCV에 FaceDetectorYN 없음")
        self.assertEqual(faces.detect_faces(np.full((400, 300, 3), 255, np.uint8)), [])

    def test_missing_model_means_no_face(self):
        with mock.patch.object(faces, "MODEL_PATH", ROOT / "nope.onnx"):
            self.assertEqual(faces.detect_faces(np.full((400, 300, 3), 255, np.uint8)), [])

    def test_real_photos(self):
        photo, anime = INPUT / "photo2_stage.jpg", INPUT / "illust1_color.jpg"
        if not (photo.exists() and anime.exists() and hasattr(cv2, "FaceDetectorYN")):
            self.skipTest("input/ 샘플 없음")
        self.assertEqual(len(faces.detect_faces(cv2.imread(str(photo)))), 1)
        self.assertEqual(faces.detect_faces(cv2.imread(str(anime))), [])


class DetectTest(unittest.TestCase):
    def test_coordinates_return_to_full_size(self):
        img = np.zeros((1600, 1200, 3), np.uint8)          # 검출은 긴 변 800px에서 → 좌표 ×2
        seen = []

        def det(small):
            seen.append(small.shape)
            return np.array([raw(100, 50, 60, 80, 0.9)])

        f = faces.detect_faces(img, detector=det)
        self.assertEqual(seen[0][:2], (800, 600))
        self.assertEqual(len(f), 1)
        np.testing.assert_allclose(f[0].box, [200, 100, 120, 160])
        self.assertEqual(f[0].landmarks.shape, (5, 2))
        np.testing.assert_allclose(f[0].landmarks[0], [200 + 120 * 0.3, 100 + 160 * 0.4])
        self.assertAlmostEqual(f[0].score, 0.9, places=5)

    def test_filters_low_score_and_tiny_and_sorts(self):
        img = np.zeros((800, 600, 3), np.uint8)
        rows = [raw(10, 10, 60, 70, 0.75), raw(200, 200, 80, 90, 0.95),
                raw(300, 300, 50, 60, 0.5),                  # 신뢰도 낮음
                raw(400, 400, 12, 14, 0.99)]                 # 폭 12 < 600*3% = 18
        f = faces.detect_faces(img, detector=fake(rows))
        self.assertEqual([round(x.score, 2) for x in f], [0.95, 0.75])

    def test_detector_error_means_no_face(self):
        def boom(img):
            raise cv2.error("x")
        self.assertEqual(faces.detect_faces(np.zeros((50, 50, 3), np.uint8), detector=boom), [])

    def test_scaled(self):
        f = faces.Face(np.array([10.0, 20, 30, 40]), np.full((5, 2), 10.0), 0.9)
        g = f.scaled(0.5, -1, 2)
        np.testing.assert_allclose(g.box, [4, 12, 15, 20])
        np.testing.assert_allclose(g.landmarks[0], [4, 7])


def face_at(x, y, w, h):
    return faces.Face(np.array([x, y, w, h], float), np.zeros((5, 2)), 0.9)


class FrameTest(unittest.TestCase):
    def test_bust_box_shape_and_position(self):
        f = face_at(500, 300, 100, 130)
        x0, y0, x1, y1 = faces.frame_box(f, "bust", 1156, 1440)
        self.assertAlmostEqual(x1 - x0, 350, delta=1)                 # 폭 3.5w
        self.assertAlmostEqual(y1 - y0, 437.5, delta=1)               # 높이 1.25 × 폭
        self.assertAlmostEqual((x0 + x1) / 2, 550, delta=1)           # 얼굴 가운데
        self.assertAlmostEqual(y0, 300 - 0.6 * 130, delta=1)          # 머리 위 여유

    def test_face_box_is_square_around_face(self):
        x0, y0, x1, y1 = faces.frame_box(face_at(500, 300, 100, 130), "face", 1156, 1440)
        self.assertAlmostEqual(x1 - x0, 234, delta=1)                 # 1.8 × max(w, h)
        self.assertAlmostEqual(y1 - y0, 234, delta=1)
        self.assertAlmostEqual((x0 + x1) / 2, 550, delta=1)
        self.assertAlmostEqual((y0 + y1) / 2, 365, delta=1)

    def test_box_is_pushed_inside_image(self):
        x0, y0, x1, y1 = faces.frame_box(face_at(-20, -30, 100, 130), "bust", 1156, 1440)
        self.assertEqual((x0, y0), (0, 0))
        self.assertAlmostEqual(x1 - x0, 350, delta=1)                 # 크기는 유지하고 밀어 넣음
        x0, y0, x1, y1 = faces.frame_box(face_at(1100, 1400, 100, 130), "face", 1156, 1440)
        self.assertEqual((x1, y1), (1156, 1440))

    def test_box_larger_than_image_shrinks(self):
        x0, y0, x1, y1 = faces.frame_box(face_at(100, 50, 300, 350), "bust", 800, 600)
        self.assertTrue(0 <= x0 < x1 <= 800 and 0 <= y0 < y1 <= 600)

    def test_auto_picks_bust_for_small_face(self):
        kind, box, note = faces.choose_frame([face_at(500, 300, 230, 300)], 1156, 1440, 100, "auto")
        self.assertEqual(kind, "bust")                                # 100 × 300/1440 = 20.8mm < 25
        self.assertIsNotNone(box)
        self.assertIn("상반신", note)
        self.assertIn("21mm", note)

    def test_auto_keeps_full_for_big_face_or_big_paper(self):
        self.assertEqual(faces.choose_frame([face_at(400, 300, 300, 400)], 1156, 1440, 100, "auto"),
                         ("full", None, ""))                          # 27.8mm
        self.assertEqual(faces.choose_frame([face_at(500, 300, 230, 300)], 1156, 1440, 150, "auto")[:2],
                         ("full", None))                              # 31mm

    def test_auto_full_without_face_or_with_many(self):
        self.assertEqual(faces.choose_frame([], 1156, 1440, 100, "auto"), ("full", None, ""))
        two = [face_at(100, 100, 50, 60), face_at(600, 100, 50, 60)]
        self.assertEqual(faces.choose_frame(two, 1156, 1440, 100, "auto")[:2], ("full", None))

    def test_manual_choices(self):
        f = [face_at(500, 300, 100, 130)]
        self.assertEqual(faces.choose_frame(f, 1156, 1440, 100, "full"), ("full", None, ""))
        kind, box, _ = faces.choose_frame(f, 1156, 1440, 100, "face")
        self.assertEqual(kind, "face")
        self.assertEqual(box, faces.frame_box(f[0], "face", 1156, 1440))
        self.assertEqual(faces.choose_frame([], 1156, 1440, 100, "bust"),
                         ("full", None, "얼굴을 찾지 못해 전체로 그립니다"))


if __name__ == "__main__":
    unittest.main()
