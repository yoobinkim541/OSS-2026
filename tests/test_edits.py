"""획 편집 함수와 모양 기반 재적용."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import edits  # noqa: E402

LINE = np.array([[0, 0], [10, 0], [20, 0], [30, 0]], float)


class PointOpsTest(unittest.TestCase):
    def test_move_delete_insert(self):
        m = edits.move_point(LINE, 1, (10, 5))
        self.assertEqual(m[1].tolist(), [10, 5])
        self.assertEqual(LINE[1].tolist(), [10, 0])            # 원본은 그대로
        self.assertEqual(len(edits.delete_points(LINE, [1, 2])), 2)
        self.assertEqual(edits.insert_point(LINE, 0, (5, 1))[1].tolist(), [5, 1])
        with self.assertRaises(edits.EditError):
            edits.delete_points(LINE, [0, 1, 2])               # 2개 미만이 남음
        with self.assertRaises(edits.EditError):
            edits.move_point(LINE, 9, (0, 0))

    def test_smooth_keeps_endpoints_and_reduces_zigzag(self):
        zig = np.array([[x, 3 * (x % 2)] for x in range(0, 40)], float)
        sm = edits.smooth(zig, 3)
        self.assertEqual(sm[0].tolist(), zig[0].tolist())
        self.assertEqual(sm[-1].tolist(), zig[-1].tolist())
        self.assertLess(np.abs(np.diff(edits.densify(sm)[:, 1])).max(), 1.5)
        with self.assertRaises(edits.EditError):
            edits.smooth(zig, 9)

    def test_split_and_join_roundtrip(self):
        a, b = edits.split(LINE, 2)
        self.assertEqual(a[-1].tolist(), b[0].tolist())
        j = edits.join(b[::-1], a)                            # 방향이 달라도 가까운 끝끼리
        self.assertAlmostEqual(float(np.hypot(*np.diff(j, axis=0).T).sum()), 30.0)   # 원래 길이 그대로
        with self.assertRaises(edits.EditError):
            edits.split(LINE, 0)


class RemoveMatchingTest(unittest.TestCase):
    def test_removed_shape_matches_nearby_recomputed_stroke(self):
        old = np.array([[10, 10], [90, 10]], float)
        new_same = np.array([[11, 11], [89, 11]], float)       # 다시 계산해 1px 어긋난 같은 선
        other = np.array([[10, 50], [90, 50]], float)
        keep, hit = edits.remove_matching([new_same, other], [old, np.array([[0, 90], [5, 95]], float)],
                                          (100, 100))
        self.assertEqual(keep, [1])
        self.assertEqual(hit, [True, False])                    # 두 번째 지운 모양은 대상 없음 -> 미적용

    def test_no_removed_keeps_all(self):
        self.assertEqual(edits.remove_matching([LINE], [], (10, 40)), ([0], []))


if __name__ == "__main__":
    unittest.main()
