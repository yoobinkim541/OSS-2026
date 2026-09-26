"""RViz 3D 환경 설치 도우미 (WSL·네트워크는 가짜로 대체 — CI에서도 동작)."""

import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mirobot_sketch import rviz_setup as rs  # noqa: E402

SCRIPT = ROOT / "packaging" / "wsl" / "setup_ros_env.sh"


def cp(rc=0, out=b""):
    return subprocess.CompletedProcess([], rc, out, b"")


class FakeWsl:
    """wsl.exe 흉내: 배포판 목록(UTF-16), 상태, 배포판 안 확인 명령의 성공 여부."""

    def __init__(self, wsl=True, distros=("Ubuntu-22.04",), env_ok=(), verify_ok=()):
        self.wsl, self.distros = wsl, list(distros)
        self.env_ok, self.verify_ok = set(env_ok), set(verify_ok)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if not self.wsl:
            raise FileNotFoundError("wsl.exe")
        if cmd[1:2] == ["--status"]:
            return cp(0)
        if cmd[1:3] == ["-l", "-q"]:
            return cp(0, ("\r\n".join(self.distros) + "\r\n").encode("utf-16-le"))
        if cmd[1] == "--import":
            self.distros.append(cmd[2])
            self.env_ok.add(cmd[2])
            self.verify_ok.add(cmd[2])
            return cp(0)
        if cmd[1] == "--unregister":
            self.distros.remove(cmd[2])
            return cp(0)
        if cmd[1] == "-d":
            name, script = cmd[2], cmd[-1]
            ok = name in (self.verify_ok if "X11" in script else self.env_ok)
            return cp(0 if ok else 1)
        return cp(1)


class FakeResp:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.body = status, body
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}
        self.text = body.decode("utf-8", "replace")

    def iter_content(self, n):
        for i in range(0, len(self.body), 3):
            yield self.body[i:i + 3]

    def json(self):
        return json.loads(self.body)


class SetupScriptTest(unittest.TestCase):
    def test_script_contents(self):
        src = SCRIPT.read_bytes()
        self.assertNotIn(b"\r\n", src)                       # WSL bash는 CRLF를 못 읽음
        text = src.decode("utf-8")
        for needle in ("set -euo pipefail", "c0a7ad4", "--packages-select wlkata_mirobot_description",
                       "textures", "ros-humble-rviz2", "ros-humble-robot-state-publisher", "SETUP_OK",
                       "--image", "default=mirobot", " g++",
                       "share/wlkata_mirobot_description/package.xml"):
            self.assertIn(needle, text, needle)

    def test_script_syntax(self):
        bash = shutil.which("bash")
        if not bash or sys.platform == "win32":
            self.skipTest("리눅스 bash 없음 (Windows에서는 CI Ubuntu에서 검사)")
        r = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class CheckTest(unittest.TestCase):
    def test_no_wsl(self):
        st = rs.check(run=FakeWsl(wsl=False))
        self.assertEqual([s.state for s in st], ["missing", "blocked", "blocked"])
        self.assertIn("관리자", st[0].hint)

    def test_no_distro_then_ready(self):
        self.assertEqual([s.state for s in rs.check(run=FakeWsl())], ["ok", "missing", "blocked"])
        w = FakeWsl(distros=["Ubuntu", rs.DISTRO], env_ok=[rs.DISTRO], verify_ok=[rs.DISTRO])
        self.assertEqual([s.state for s in rs.check(run=w)], ["ok", "ok", "ok"])

    def test_verify_failure_is_reported(self):
        w = FakeWsl(distros=[rs.DISTRO], env_ok=[rs.DISTRO])
        st = rs.check(run=w)
        self.assertEqual([s.state for s in st], ["ok", "ok", "missing"])
        self.assertTrue(st[2].hint)


class DownloadTest(unittest.TestCase):
    def test_resume_with_range_and_restart_when_ignored(self):
        body = b"0123456789abcdef"
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "img.tar.gz"
            part = Path(str(dest) + ".part")
            part.write_bytes(body[:5])
            seen = []

            def get206(url, headers=None, **kw):
                seen.append(headers)
                return FakeResp(206, body[5:])

            rs.download("u", dest, get=get206)
            self.assertEqual(seen[0], {"Range": "bytes=5-"})
            self.assertEqual(dest.read_bytes(), body)
            part.write_bytes(b"garbage")                  # 서버가 Range를 무시하고 200 -> 처음부터
            dest.unlink()
            rs.download("u", dest, get=lambda url, headers=None, **kw: FakeResp(200, body))
            self.assertEqual(dest.read_bytes(), body)

    def test_cancel_keeps_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / "img.tar.gz"
            with self.assertRaises(rs.SetupError):
                rs.download("u", dest, get=lambda *a, **k: FakeResp(200, b"x" * 30), should_cancel=lambda: True)
            self.assertFalse(dest.exists())

    def test_http_error(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(rs.SetupError):
            rs.download("u", Path(d) / "a", get=lambda *a, **k: FakeResp(404))


class InstallTest(unittest.TestCase):
    def make_image(self, d):
        gz = Path(d) / "img.tar.gz"
        with gzip.open(gz, "wb") as g:
            g.write(b"rootfs" * 100)
        return gz, hashlib.sha256(gz.read_bytes()).hexdigest()

    def fake_get(self, gz, sha):
        def get(url, headers=None, **kw):
            if url.endswith(".sha256"):
                return FakeResp(200, f"{sha}  img.tar.gz\n".encode())
            return FakeResp(200, gz.read_bytes())
        return get

    def patches(self, d, free=100 * 2**30):
        return (mock.patch.object(rs, "install_dir", lambda: Path(d) / "wsl"),
                mock.patch.object(rs.shutil, "disk_usage", lambda p: mock.Mock(free=free)))

    def test_full_install_imports_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = self.patches(d)
            with p1, p2:
                gz, sha = self.make_image(d)
                w = FakeWsl()
                st = rs.install(run=w, get=self.fake_get(gz, sha), version="9.9.9")
                self.assertEqual([s.state for s in st], ["ok", "ok", "ok"])
                imp = next(c for c in w.calls if c[1] == "--import")
                self.assertEqual(imp[2], rs.DISTRO)
                self.assertEqual(imp[-2:], ["--version", "2"])
                self.assertFalse(list((Path(d) / "wsl").glob("*.tar*")))      # 받은 파일은 지움

    def test_already_installed_does_not_download(self):
        w = FakeWsl(distros=[rs.DISTRO], env_ok=[rs.DISTRO], verify_ok=[rs.DISTRO])
        get = mock.Mock()
        rs.install(run=w, get=get, version="9.9.9")
        get.assert_not_called()

    def test_sha_mismatch_and_bad_gzip_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = self.patches(d)
            with p1, p2:
                gz, sha = self.make_image(d)
                with self.assertRaises(rs.SetupError) as cm:
                    rs.install(run=FakeWsl(), get=self.fake_get(gz, "0" * 64), version="9.9.9")
                self.assertIn("SHA256", cm.exception.message)
                self.assertFalse(list((Path(d) / "wsl").glob("*.tar.gz")))    # 다음엔 새로 받게 지움
            bad = Path(d) / "bad.gz"
            bad.write_bytes(b"not gzip")
            with self.assertRaises(rs.SetupError):
                rs.gunzip(bad, Path(d) / "out.tar")

    def test_low_disk_space(self):
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = self.patches(d, free=1 * 2**30)
            with p1, p2, self.assertRaises(rs.SetupError) as cm:
                rs.import_distro(Path(d) / "x.tar", run=FakeWsl())
            self.assertIn("공간", cm.exception.message)

    def test_wsl_missing_stops_before_download(self):
        with self.assertRaises(rs.SetupError) as cm:
            rs.install(run=FakeWsl(wsl=False), get=mock.Mock(), version="9.9.9")
        self.assertEqual(cm.exception.step, "wsl")


class UrlAndCommandsTest(unittest.TestCase):
    def test_image_urls_prefer_same_version_then_latest_release(self):
        url, sha = rs.image_urls("0.3.0", get=lambda url, **kw: FakeResp(200, b"abc  x\n"))
        self.assertTrue(url.startswith("https://github.com/yoobinkim541/OSS-2026-Mirobot-Photo-Sketch/releases/"))
        self.assertTrue(url.endswith("/v0.3.0/MirobotSketch-ROS-humble-0.3.0.tar.gz"))
        self.assertEqual(sha, url + ".sha256")

        def get_api(url, **kw):
            if "api.github.com" in url:
                return FakeResp(200, json.dumps([
                    {"tag_name": "v0.4.0", "assets": []},
                    {"tag_name": "v0.3.0", "assets": [
                        {"name": "MirobotSketch-ROS-humble-0.3.0.tar.gz", "browser_download_url": "U"},
                        {"name": "MirobotSketch-ROS-humble-0.3.0.tar.gz.sha256", "browser_download_url": "S"}]},
                ]).encode())
            return FakeResp(404)

        self.assertEqual(rs.image_urls("0.5.0", get=get_api), ("U", "S"))

    def test_admin_and_manual_commands(self):
        popen = mock.Mock()
        rs.install_wsl_feature(popen=popen)
        cmd = " ".join(popen.call_args.args[0])
        self.assertIn("--no-distribution", cmd)
        self.assertIn("RunAs", cmd)
        popen.reset_mock()
        rs.manual_install(run=FakeWsl(distros=["Ubuntu"]), popen=popen)       # 22.04 없음 -> 배포판부터
        self.assertIn("Ubuntu-22.04", popen.call_args.args[0])
        self.assertIn("--install", popen.call_args.args[0])
        popen.reset_mock()
        rs.manual_install(run=FakeWsl(distros=["Ubuntu-22.04"]), popen=popen)
        self.assertTrue(popen.call_args.args[0][-1].endswith("setup_ros_env.sh"))
        self.assertTrue(rs.script_path().exists())


if __name__ == "__main__":
    unittest.main()
