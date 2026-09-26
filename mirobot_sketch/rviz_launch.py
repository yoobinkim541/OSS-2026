"""
GUI에서 RViz 3D 재생 창 열기 (Windows → WSL2 Ubuntu + ROS 2 Humble)
====================================================================
시뮬레이션 결과를 관절 궤적 JSON으로 저장하고, ROS가 설치된 WSL 배포판에서
sim/run_rviz.sh(robot_state_publisher + rviz2 + rviz_playback.py)를 백그라운드로 실행합니다.
RViz 창은 WSLg로 Windows 바탕화면에 뜹니다. 창을 닫으면 재생도 함께 멈춥니다.

필요: WSL 배포판에 /opt/ros/humble 과 ~/mirobot_ws (wlkata_mirobot_description 빌드).
배포판을 직접 고르려면 환경 변수 MIROBOT_WSL_DISTRO.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import paths

ROS_CHECK = "test -f /opt/ros/humble/setup.bash && test -f $HOME/mirobot_ws/install/setup.bash"
SETUP_HINT = ("RViz 3D 보기는 WSL2 Ubuntu 22.04에 ROS 2 Humble과 ~/mirobot_ws"
              "(wlkata_mirobot_description)가 설치된 PC에서만 됩니다.\n"
              "그 외에는 '로봇 시뮬레이션' 결과(관절 여유)로 확인하세요.")

_distro_cache = {}


class RvizUnavailable(RuntimeError):
    pass


def _no_window():
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def to_wsl_path(p):
    """C:\\a\\b → /mnt/c/a/b (이미 POSIX 경로면 그대로)."""
    s = str(Path(p).resolve()) if sys.platform == "win32" else str(p)
    if len(s) > 2 and s[1] == ":":
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def scripts_dir():
    """run_rviz.sh·rviz_playback.py·rviz 설정이 있는 폴더 (저장소 sim/ 또는 exe에 포함된 sim/)."""
    root = paths.repo_root()
    if root is not None:
        return root / "sim"
    if paths.FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "sim"
    return None


def list_distros(run=subprocess.run):
    try:
        r = run(["wsl.exe", "-l", "-q"], capture_output=True, timeout=20, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError):
        return []
    raw = r.stdout or b""
    text = raw.decode("utf-16-le", errors="ignore") if b"\x00" in raw else raw.decode(errors="ignore")
    names = [n.strip().strip("\x00") for n in text.splitlines()]
    return [n for n in names if n and not n.startswith("docker-desktop")]


def find_ros_distro(run=subprocess.run):
    """ROS 2 Humble + mirobot_ws가 있는 WSL 배포판 이름. 없으면 None. (한 번 찾으면 기억)"""
    if "name" in _distro_cache:
        return _distro_cache["name"]
    wanted = os.environ.get("MIROBOT_WSL_DISTRO")
    candidates = [wanted] if wanted else sorted(list_distros(run), key=lambda n: "22.04" not in n)
    found = None
    for d in candidates:
        try:
            r = run(["wsl.exe", "-d", d, "--", "bash", "-c", ROS_CHECK], capture_output=True, timeout=60,
                    creationflags=_no_window())
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            found = d
            break
    _distro_cache["name"] = found
    return found


def launch(traj_path, speed=20, follow=None, run=subprocess.run, popen=subprocess.Popen):
    """RViz 재생을 백그라운드로 시작하고 Popen을 돌려줌. 쓸 수 없으면 RvizUnavailable.
    follow=진행 파일이면 반복 재생 대신 로봇 진행을 실시간으로 따라감."""
    if sys.platform != "win32":
        raise RvizUnavailable("RViz 창 열기는 Windows + WSL에서만 지원합니다. Linux에서는 sim/run_rviz.sh를 직접 실행하세요.")
    sdir = scripts_dir()
    if sdir is None or not (sdir / "run_rviz.sh").exists():
        raise RvizUnavailable("RViz 실행 스크립트(sim/run_rviz.sh)를 찾을 수 없습니다.")
    distro = find_ros_distro(run)
    if not distro:
        raise RvizUnavailable(SETUP_HINT)
    cmd = f"bash {shlex.quote(to_wsl_path(sdir / 'run_rviz.sh'))} {shlex.quote(to_wsl_path(traj_path))} {float(speed):g}"
    if follow is not None:
        cmd += f" {shlex.quote(to_wsl_path(follow))}"
    log = open(paths.output_dir() / "rviz_launch.log", "w", encoding="utf-8")
    try:
        return popen(["wsl.exe", "-d", distro, "--", "bash", "-lc", cmd], stdout=log, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, creationflags=_no_window())
    finally:
        log.close()   # 자식 프로세스가 핸들을 물려받았으므로 여기서 닫아도 됨
