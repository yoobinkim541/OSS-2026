"""리팩터링 전후 run_pipeline() 결과가 같은지 (기준값: tests/golden.py --write)."""

import json
import unittest

import golden


class GoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not golden.GOLDEN.exists():
            raise unittest.SkipTest("기준값 없음: python tests/golden.py --write")
        cls.expected = json.loads(golden.GOLDEN.read_text(encoding="utf-8"))

    def test_synthetic_same_as_before_refactor(self):
        got = golden.compute_all(include_samples=False)["synthetic"]
        self.assertEqual(got, self.expected["synthetic"])

    def test_samples_same_as_before_refactor(self):
        exp = self.expected.get("samples") or {}
        if not exp or not (golden.ROOT / "input").exists():
            self.skipTest("샘플 이미지 없음 (input/은 저장소 밖)")
        got = golden.compute_all()["samples"]
        for k, v in exp.items():
            if k in got:
                self.assertEqual(got[k], v, k)


if __name__ == "__main__":
    unittest.main()
