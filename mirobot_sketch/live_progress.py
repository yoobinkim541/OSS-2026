"""
실시간 드로잉 진행 파일과 RViz 따라가기 위치 계산
=================================================
GUI(Windows)의 실행 스레드가 로봇의 ok 응답마다 진행 파일을 쓰고, WSL의 sim/rviz_playback.py
--follow가 그 파일을 읽어 로봇팔·펜 자국을 같은 명령 위치로 옮깁니다.

표준 라이브러리만 씁니다 (WSL의 ROS 파이썬에서도 불러 쓰기 때문).
진행 파일 형식: {"run_id", "state": homing|running|stopped|done|error, "acked", "total", "t", "speed",
                "tcp_mm": null(실제 좌표 읽기 자리), "trajectory", "message"}
"""

import bisect
import json
import os
import sys
import time

FINAL_STATES = ("stopped", "error", "done")


class ProgressWriter:
    """임시 파일에 쓴 뒤 os.replace로 바꿔 넣음 (읽는 쪽이 반쪽 JSON을 보지 않게)."""

    def __init__(self, path):
        self.path = str(path)
        self.tmp = self.path + ".tmp"
        self.fields = {"tcp_mm": None}

    def write(self, **fields):
        self.fields.update(fields)
        self.fields["t"] = time.time()
        data = json.dumps(self.fields, ensure_ascii=False)
        with open(self.tmp, "w", encoding="utf-8") as f:
            f.write(data)
        for attempt in range(20):   # Windows: 읽는 쪽이 잠깐 열고 있으면 교체가 실패할 수 있음
            try:
                os.replace(self.tmp, self.path)
                break
            except PermissionError:
                time.sleep(0.005 * (attempt + 1))
        return dict(self.fields)


def read_progress(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def to_local_path(p):
    """진행 파일에 적힌 Windows 경로를 이 컴퓨터에서 열 수 있는 경로로 (WSL이면 /mnt/c/...)."""
    s = str(p)
    if sys.platform != "win32" and len(s) > 2 and s[1] == ":":
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


class FollowTrack:
    """궤적 점(cmd 번호)과 명령별 속도로 '지금 보여 줄 점 번호'를 계산."""

    def __init__(self, points, cmd_feed_mm_min, step_mm=1.0):
        cmds = [int(p["cmd"]) for p in points]
        self.n = len(cmds)
        self.cmd_feed = list(cmd_feed_mm_min)
        self.step = float(step_mm)
        count = max(cmds) + 1 if cmds else 0
        self.cmd_end = [bisect.bisect_right(cmds, k) - 1 for k in range(count)]   # 명령 k의 마지막 점

    def _done_index(self, acked):
        if acked <= 0 or not self.cmd_end:
            return 0
        return self.cmd_end[min(acked, len(self.cmd_end)) - 1]

    def index(self, progress, now):
        if not progress:
            return 0
        acked = int(progress.get("acked", 0))
        base = self._done_index(acked)
        if progress.get("state") != "running" or acked >= len(self.cmd_end):
            return base
        limit = self.cmd_end[acked]                           # 지금 실행 중인 명령의 끝
        feed = self.cmd_feed[acked] if acked < len(self.cmd_feed) else 0.0
        elapsed = max(0.0, now - float(progress.get("t", now)))
        ahead = int(elapsed * feed / 60.0 * float(progress.get("speed", 1.0)) / self.step)
        return min(base + ahead, limit)
