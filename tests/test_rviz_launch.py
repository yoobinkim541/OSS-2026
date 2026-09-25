"""GUI의 'RViz 3D로 보기' 실행 준비 (WSL 호출은 가짜로 대체 — CI의 Ubuntu에서도 동작)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mirobot_sketch import mirobot_sim as ms  # noqa: E402
from mirobot_sketch import rviz_launch as rl  # noqa: E402


def fake_run(ros_distro):
    def run(cmd, **kw):
        if cmd[:2] == ["wsl.exe", "-l"]:   # wsl.exe -l -q 출력은 UTF-16LE
            out = "Ubuntu\r\ndocker-desktop\r\nUbuntu-22.04\r\n".encode("utf-16-le")
            return subprocess.CompletedProcess(cmd, 0, out, b"")
        return subprocess.CompletedProcess(cmd, 0 if cmd[2] == ros_distro else 1, b"", b"")
    return run


class RvizLaunchTest(unittest.TestCase):
    def setUp(self):
        rl._distro_cache.clear()

    def test_wsl_path(self):
        with mock.patch.object(rl.sys, "platform", "linux"):
            self.assertEqual(rl.to_wsl_path("C:\\Users\\a b\\x.json"), "/mnt/c/Users/a b/x.json")
            self.assertEqual(rl.to_wsl_path("/home/u/x.json"), "/home/u/x.json")

    def test_finds_distro_with_ros_and_skips_docker(self):
        self.assertEqual(rl.list_distros(fake_run(None)), ["Ubuntu", "Ubuntu-22.04"])
        self.assertEqual(rl.find_ros_distro(fake_run("Ubuntu-22.04")), "Ubuntu-22.04")

    def test_no_ros_distro_explains_setup(self):
        popen = mock.Mock()
        with mock.patch.object(rl.sys, "platform", "win32"), mock.patch.object(rl, "_no_window", lambda: 0):
            with self.assertRaises(rl.RvizUnavailable) as cm:
                rl.launch("t.json", run=fake_run(None), popen=popen)
        self.assertIn("ROS 2 Humble", str(cm.exception))
        popen.assert_not_called()

    def test_launch_runs_script_in_found_distro(self):
        popen = mock.Mock()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rl.sys, "platform", "win32"), mock.patch.object(rl, "_no_window", lambda: 0), \
                mock.patch.object(rl.paths, "output_dir", lambda: Path(d)), \
                mock.patch.object(rl, "to_wsl_path", lambda p: "/mnt/c/" + Path(p).name):
            rl.launch(Path(d) / "my traj.json", speed=20, run=fake_run("Ubuntu-22.04"), popen=popen)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[:4], ["wsl.exe", "-d", "Ubuntu-22.04", "--"])
        self.assertEqual(argv[-1], "bash /mnt/c/run_rviz.sh '/mnt/c/my traj.json' 20")   # 공백 경로는 따옴표

    def test_repo_ships_the_scripts(self):
        d = rl.scripts_dir()
        for f in ("run_rviz.sh", "rviz_playback.py", "rviz/mirobot_sketch.rviz"):
            self.assertTrue((d / f).exists(), f)
        self.assertNotIn(b"\r\n", (d / "run_rviz.sh").read_bytes())   # WSL bash는 CRLF를 못 읽음

    def test_trajectory_doc_matches_playback_format(self):
        cfg = {"pen": {"pen_tip_offset_mm": [100, 0, 0]}}
        with mock.patch.object(ms, "pen_tip_offset", lambda c: __import__("numpy").array([100.0, 0, 0])):
            doc = ms.trajectory_doc({"samples": [([0.0] * 6, __import__("numpy").array([200.0, 0, 230]), "G01", 1)]},
                                    cfg, "x.png")
        p = doc["points"][0]
        self.assertEqual(p["pen_tip_mm"], [300.0, 0.0, 230.0])
        self.assertTrue(p["pen_down"])
        self.assertEqual(len(doc["joint_names"]), 6)


class SourceCompilesTest(unittest.TestCase):
    def test_every_module_compiles(self):
        """GUI처럼 테스트가 import하지 않는 모듈의 문법 오류도 잡음 (Tk 창 없이)."""
        import py_compile
        pkg = Path(rl.__file__).resolve().parent
        for f in sorted(pkg.rglob("*.py")):
            with self.subTest(f.name):
                py_compile.compile(str(f), doraise=True, cfile=str(Path(tempfile.gettempdir()) / "mirobot_pyc_check"))


if __name__ == "__main__":
    unittest.main()
