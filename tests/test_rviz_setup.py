"""RViz 3D 환경 설치 도우미 (WSL·네트워크는 가짜로 대체 — CI에서도 동작)."""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPT = ROOT / "packaging" / "wsl" / "setup_ros_env.sh"


class SetupScriptTest(unittest.TestCase):
    def test_script_contents(self):
        src = SCRIPT.read_bytes()
        self.assertNotIn(b"\r\n", src)                       # WSL bash는 CRLF를 못 읽음
        text = src.decode("utf-8")
        for needle in ("set -euo pipefail", "c0a7ad4", "--packages-select wlkata_mirobot_description",
                       "textures", "ros-humble-rviz2", "ros-humble-robot-state-publisher", "SETUP_OK",
                       "--image", "default=mirobot"):
            self.assertIn(needle, text, needle)

    def test_script_syntax(self):
        bash = shutil.which("bash")
        if not bash or sys.platform == "win32":
            self.skipTest("리눅스 bash 없음 (Windows에서는 CI Ubuntu에서 검사)")
        r = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
