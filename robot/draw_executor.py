"""
획 JSON -> Mirobot 펜 드로잉 실행기 (Windows 전용)
==================================================
CV/make_strokes.py 또는 GUI가 만든 sketch_strokes JSON(종이 중심 기준 mm)을
읽어 Cartesian 직선 이동 G-code로 바꾸고, 시리얼로 한 줄씩 보냅니다.

기본은 dry-run입니다: 로봇을 움직이지 않고 G-code 파일과 요약만 만듭니다.
실제로 그리려면 --execute를 붙이세요.

    python robot/draw_executor.py trajectories/orientation-test-F.json
    python robot/draw_executor.py out/photo_strokes.json --execute

실행 순서 (설계 문서 / mirobot_control.py와 같은 규칙):
  1. 다른 프로그램이 COM 포트를 열고 있지 않은지 확인
  2. --execute로 실행 -> 포트를 열면 보드가 리셋돼 Alarm 상태가 됨
  3. 안내가 나오면 중앙 버튼 2초로 호밍 -> Idle이 되면 자동으로 다음 단계
  4. 홈 자세 TCP가 종이 중심(drawing_config.json의 paper_center_tcp_mm)과 같아야
     하므로, 홈 자세에서 펜 끝이 종이 중앙에 오도록 종이를 고정해 둔다
  5. 확인 질문에 yes 입력

안전 규칙:
  - 자동 호밍을 하지 않습니다. Idle이 아니면 시작하지 않습니다.
  - 현재 TCP가 설정된 종이 중심에서 max_start_offset_mm 이상 떨어져 있으면 시작하지 않습니다.
  - 종이 범위(limits)를 벗어나는 점이 하나라도 있으면 전송 전에 거부합니다.
  - 명령마다 ok 응답을 기다립니다. Alarm / limit / error 응답이나 타임아웃이 오면
    즉시 전송을 멈추고, 복구 동작을 자동으로 하지 않습니다 (사용자 확인 대상).
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path(__file__).resolve().parent / "drawing_config.json"
RUN_LOG_DIR = ROOT / "LOG" / "runs"

ERROR_TOKENS = ("alarm", "error", "limit", "emergency")
CARTESIAN_RE = re.compile(r"Cartesian coordinate\(XYZ RxRyRz\):\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)")


# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------

def load_config(path=DEFAULT_CONFIG):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_strokes(path):
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("kind") != "sketch_strokes" or doc.get("units") != "mm":
        raise ValueError(f"sketch_strokes(mm) 형식이 아닙니다: {path}")
    strokes = [[(float(x), float(y)) for x, y in s["points_xy_mm"]] for s in doc["strokes"]]
    return doc, [s for s in strokes if len(s) >= 2]


# ---------------------------------------------------------------------------
# 계획: 종이 mm -> 로봇 TCP -> G-code
# ---------------------------------------------------------------------------

def check_limits(strokes, cfg):
    lim = cfg["limits"]
    bad = []
    for i, s in enumerate(strokes):
        for x, y in s:
            if abs(x) > lim["max_abs_paper_x_mm"] + 1e-6 or abs(y) > lim["max_abs_paper_y_mm"] + 1e-6:
                bad.append((i, x, y))
    return bad


class Planner:
    def __init__(self, cfg):
        self.cfg = cfg
        c = cfg["paper_center_tcp_mm"]
        self.cx, self.cy, self.cz = c["x"], c["y"], c["z"]
        o = cfg["orientation_deg"]
        self.abc = (o["a"], o["b"], o["c"])
        self.sy = cfg["paper_x_to_robot_y_sign"]
        self.sz = cfg["paper_y_to_robot_z_sign"]
        pen = cfg["pen"]
        self.up_dx = pen["retract_x_sign"] * pen["up_clearance_mm"]
        self.down_extra = -pen["retract_x_sign"] * pen["down_extra_mm"]  # 누르는 방향 = 후퇴의 반대
        pc = cfg["plane_compensation"]
        self.pa, self.pb = pc["a_per_mm_y"], pc["b_per_mm_z"]
        self.feeds = cfg["feeds_mm_per_min"]

    def robot_yz(self, px, py):
        return self.cy + self.sy * px, self.cz + self.sz * py

    def contact_x(self, ry, rz):
        return self.cx + self.pa * (ry - self.cy) + self.pb * (rz - self.cz) + self.down_extra

    def pose(self, px, py, pen_down):
        ry, rz = self.robot_yz(px, py)
        x = self.contact_x(ry, rz)
        if not pen_down:
            x += self.up_dx
        return x, ry, rz

    def gcode(self, pose, feed):
        x, y, z = pose
        a, b, c = self.abc
        return f"M20 G90 G01 X{x:.3f} Y{y:.3f} Z{z:.3f} A{a:.3f} B{b:.3f} C{c:.3f} F{feed:.0f}"

    def plan(self, strokes):
        """[(gcode, 설명)] 리스트. 종이 중심 펜업에서 시작해 종이 중심 펜업으로 끝납니다."""
        f = self.feeds
        cmds = [(self.gcode(self.pose(0, 0, False), f["approach"]), "center pen-up")]
        for i, s in enumerate(strokes):
            x0, y0 = s[0]
            cmds.append((self.gcode(self.pose(x0, y0, False), f["travel"]), f"stroke {i} travel"))
            cmds.append((self.gcode(self.pose(x0, y0, True), f["approach"]), f"stroke {i} pen-down"))
            for x, y in s[1:]:
                cmds.append((self.gcode(self.pose(x, y, True), f["draw"]), f"stroke {i} draw"))
            x1, y1 = s[-1]
            cmds.append((self.gcode(self.pose(x1, y1, False), f["approach"]), f"stroke {i} pen-up"))
        cmds.append((self.gcode(self.pose(0, 0, False), f["travel"]), "return center pen-up"))
        return cmds


def estimate_seconds(strokes, cfg):
    """이론상 최소 시간 (가감속/명령 지연 제외)."""
    f = cfg["feeds_mm_per_min"]
    clear = cfg["pen"]["up_clearance_mm"]
    down = up = 0.0
    pos = (0.0, 0.0)
    for s in strokes:
        up += _dist(pos, s[0])
        down += sum(_dist(a, b) for a, b in zip(s, s[1:]))
        pos = s[-1]
    up += _dist(pos, (0.0, 0.0))
    approach = clear * (2 * len(strokes) + 1)
    return (down / f["draw"] + up / f["travel"] + approach / f["approach"]) * 60.0, down, up


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# 시리얼
# ---------------------------------------------------------------------------

class ControllerError(RuntimeError):
    pass


class MirobotLink:
    """시리얼 연결을 한 번만 열고 재사용합니다. ser는 테스트용 가짜 객체로 바꿀 수 있습니다."""

    def __init__(self, ser, verbose=False):
        self.ser = ser
        self.verbose = verbose

    @classmethod
    def open(cls, port, baud, verbose=False):
        import serial

        ser = serial.Serial(port, baud, timeout=0.2)
        time.sleep(2)  # 포트를 열면 보드가 리셋됨 -> 부팅 대기
        ser.read(ser.in_waiting or 1)
        return cls(ser, verbose)

    def _readline(self):
        return self.ser.readline().decode(errors="replace").strip()

    def query_status(self, timeout=2.0):
        """(상태 문자열, (x, y, z) 또는 None, 원문)."""
        self.ser.reset_input_buffer()
        self.ser.write(b"?\r\n")
        deadline = time.monotonic() + timeout
        buf = ""
        while time.monotonic() < deadline:
            buf += self._readline()
            if "<" in buf and ">" in buf:
                break
        if "<" not in buf:
            return "unknown", None, buf
        body = buf[buf.index("<") + 1:]
        state = body.split(",")[0]
        m = CARTESIAN_RE.search(buf)
        tcp = tuple(float(v) for v in m.groups()) if m else None
        return state, tcp, buf

    def wait_idle(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state, tcp, raw = self.query_status()
            if state == "Idle":
                return tcp
            if any(t in raw.lower() for t in ERROR_TOKENS):
                raise ControllerError(f"Idle 대기 중 오류 상태: {raw}")
            time.sleep(0.5)
        raise ControllerError("Idle 대기 시간 초과")

    def send_and_ack(self, line, timeout):
        """한 줄을 보내고 ok를 기다립니다. 오류 응답이나 타임아웃이면 ControllerError."""
        self.ser.write((line + "\r\n").encode("ascii"))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self._readline()
            if not resp:
                continue
            if self.verbose:
                print(f"    <- {resp}")
            low = resp.lower()
            if any(t in low for t in ERROR_TOKENS):
                raise ControllerError(f"컨트롤러 오류 응답: {resp}")
            if low.startswith("ok"):
                return
        raise ControllerError(f"ok 응답 시간 초과: {line}")

    def wait_for_homing(self, timeout, progress=print):
        """포트를 열면 보드가 리셋돼 Alarm으로 시작합니다. 사용자가 물리 버튼으로
        호밍해 Idle이 될 때까지 기다립니다 (자동 호밍 명령은 보내지 않음).
        반환: (상태, TCP). 시간 안에 Idle이 안 되면 마지막 상태를 그대로 반환."""
        deadline = time.monotonic() + timeout
        last = None
        state, tcp = "unknown", None
        while time.monotonic() < deadline:
            state, tcp, _ = self.query_status()
            if state != last:
                progress(f"  컨트롤러 상태: {state}")
                if state == "Alarm":
                    progress("  -> 중앙 네비게이션 버튼을 2초 눌러 호밍하세요. Idle이 되면 자동으로 계속합니다.")
                last = state
            if state == "Idle":
                break
            time.sleep(1.0)
        return state, tcp

    def close(self):
        self.ser.close()


def execute(link, cmds, cfg, progress=print):
    """계획된 명령을 순서대로 보냅니다. 반환: 실행 결과 dict. 오류 시 즉시 멈춥니다."""
    started = time.monotonic()
    sent = 0
    try:
        for i, (line, label) in enumerate(cmds):
            link.send_and_ack(line, cfg["ack_timeout_s"])
            sent = i + 1
            if label.endswith("pen-down") or i == len(cmds) - 1:
                progress(f"  [{sent}/{len(cmds)}] {label}")
        link.wait_idle(cfg["idle_timeout_s"])
        return {"result": "completed", "commands_sent": sent, "elapsed_s": round(time.monotonic() - started, 1)}
    except ControllerError as e:
        return {"result": "stopped_on_error", "error": str(e), "commands_sent": sent,
                "failed_command": cmds[sent][1] if sent < len(cmds) else None,
                "elapsed_s": round(time.monotonic() - started, 1)}
    except KeyboardInterrupt:
        return {"result": "interrupted_by_user", "commands_sent": sent,
                "elapsed_s": round(time.monotonic() - started, 1)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("strokes_json", type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--execute", action="store_true", help="실제 로봇으로 전송 (없으면 dry-run)")
    ap.add_argument("--gcode-out", type=Path, help="dry-run G-code 저장 경로 (기본: 입력 옆 .gcode)")
    ap.add_argument("--verbose", action="store_true", help="컨트롤러 응답을 모두 출력")
    args = ap.parse_args()

    cfg = load_config(args.config)
    doc, strokes = load_strokes(args.strokes_json)
    if not strokes:
        print("그릴 획이 없습니다.")
        return 1

    bad = check_limits(strokes, cfg)
    if bad:
        i, x, y = bad[0]
        print(f"거부: 종이 허용 범위를 벗어난 점 {len(bad)}개 (예: 획 {i}, x={x:.1f}, y={y:.1f} mm).")
        print("CV 단계에서 --box를 줄이거나 drawing_config.json의 limits를 확인하세요.")
        return 2

    planner = Planner(cfg)
    cmds = planner.plan(strokes)
    est, down, up = estimate_seconds(strokes, cfg)
    ys = [planner.robot_yz(x, y)[0] for s in strokes for x, y in s]
    zs = [planner.robot_yz(x, y)[1] for s in strokes for x, y in s]

    print(f"입력: {args.strokes_json}")
    print(f"획 {len(strokes)}개, G-code {len(cmds)}줄")
    print(f"펜다운 {down:.0f} mm, 펜업 이동 {up:.0f} mm, 이론상 최소 {est:.0f} s")
    print(f"로봇 Y 범위 {min(ys):.1f} ~ {max(ys):.1f}, Z 범위 {min(zs):.1f} ~ {max(zs):.1f} mm")
    if cfg.get("_axis_sign_status") != "verified":
        print("주의: 좌우 부호(paper_x_to_robot_y_sign)가 아직 미검증입니다. orientation-test-F로 먼저 확인하세요.")
    if cfg["plane_compensation"]["status"] != "verified":
        print("주의: 종이 평면 보정이 아직 없습니다. 위치에 따라 펜 접촉이 달라질 수 있습니다.")

    if not args.execute:
        out = args.gcode_out or args.strokes_json.with_suffix(".gcode")
        with open(out, "w", encoding="ascii") as f:
            for line, label in cmds:
                f.write(f"{line} ; {label}\n")
        print(f"dry-run: 로봇을 움직이지 않았습니다. G-code 저장: {out}")
        return 0

    link = MirobotLink.open(cfg["port"], cfg["baud"], args.verbose)
    try:
        state, tcp = link.wait_for_homing(cfg["idle_timeout_s"])
        print(f"컨트롤러 상태: {state}, TCP: {tcp}")
        if state != "Idle":
            print("Idle이 되지 않아 시작하지 않습니다.")
            return 3
        if tcp is None:
            print("TCP 좌표를 읽지 못해 시작 위치를 확인할 수 없습니다. 중단합니다.")
            return 3
        c = cfg["paper_center_tcp_mm"]
        off = ((tcp[0] - c["x"]) ** 2 + (tcp[1] - c["y"]) ** 2 + (tcp[2] - c["z"]) ** 2) ** 0.5
        if off > cfg["max_start_offset_mm"]:
            print(f"현재 TCP가 종이 중심 설정에서 {off:.1f} mm 떨어져 있습니다. 중단합니다.")
            return 3
        if input("종이·펜·주변을 확인했으면 yes 입력: ").strip().lower() != "yes":
            print("취소했습니다.")
            return 0

        result = execute(link, cmds, cfg)
    finally:
        link.close()

    print(f"결과: {result}")
    if result["result"] != "completed":
        print("자동 복구를 하지 않았습니다. 펜과 로봇 상태를 확인한 뒤 수동으로 조치하세요.")

    RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run = {
        "started_local": stamp,
        "strokes_json": str(args.strokes_json),
        "stroke_count": len(strokes),
        "command_count": len(cmds),
        "estimated_min_time_s": round(est, 1),
        "config_snapshot": cfg,
        "source": doc.get("source", {}),
        **result,
        "visual_verification": "pending",
    }
    with open(RUN_LOG_DIR / f"run-{stamp}.json", "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1)
    print(f"실행 기록: LOG/runs/run-{stamp}.json (종이 사진 확인 결과를 visual_verification에 적어두세요)")
    return 0 if result["result"] == "completed" else 4


if __name__ == "__main__":
    sys.exit(main())
