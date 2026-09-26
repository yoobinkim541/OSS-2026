#!/usr/bin/env python3
"""
시뮬레이션 관절 궤적을 RViz의 Mirobot 3D 모델로 재생합니다 (WSL2 / ROS 2 Humble).

sim/mirobot_sim.py --export 로 만든 JSON을 읽어 /joint_states를 발행하고,
종이(A4 테두리), 펜홀더+펜(플랜지 -> 펜 끝), 펜 끝이 종이에 남긴 자국을
/sketch_markers로 표시합니다. 펜 끝 위치는 drawing_config.json의 pen_tip_offset_mm.
보통은 sim/run_rviz.sh 로 robot_state_publisher, rviz2와 함께 실행합니다.

    python3 sim/rviz_playback.py traj.json --speed 10 --loop          # 반복 재생
    python3 sim/rviz_playback.py traj.json --follow live_progress.json  # 로봇 진행 따라가기 (GUI '로봇으로 그리기')

따라가기 모드는 mirobot_sketch.live_progress를 불러 씁니다 (run_rviz.sh가 PYTHONPATH를 맞춤).
"""

import argparse
import json
import time

import rclpy
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Point
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

REAL_FEED_MM_S = 300 / 60.0  # 펜다운 속도 300 mm/min 기준 1mm 샘플 = 0.2 s
FOLLOW_PERIOD_S = 0.05       # 따라가기: 진행 파일을 읽는 간격


def pt(mm):
    return Point(x=mm[0] / 1000.0, y=mm[1] / 1000.0, z=mm[2] / 1000.0)


class Playback(Node):
    def __init__(self, traj, speed, loop, start_timer=True):
        super().__init__("sketch_playback")
        self.traj = traj
        self.points = traj["points"]
        self.loop = loop
        self.i = 0
        self.js_pub = self.create_publisher(JointState, "joint_states", 10)
        qos = QoSProfile(depth=5, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.mk_pub = self.create_publisher(MarkerArray, "sketch_markers", qos)
        self.trail = []
        if start_timer:
            period = (1.0 / REAL_FEED_MM_S) / speed
            self.timer = self.create_timer(period, self.tick)
        self.get_logger().info(f"{traj.get('source')}: {len(self.points)} samples, x{speed} speed")

    @staticmethod
    def tip(p):
        return p.get("pen_tip_mm", p["tcp_mm"])

    def paper_marker(self):
        c = self.tip(self.points[0])  # 시작점 = 종이 중심에 펜 끝이 닿은 상태
        m = Marker(type=Marker.LINE_STRIP, action=Marker.ADD, ns="paper", id=0)
        m.header.frame_id = "base_link"
        m.scale.x = 0.002
        m.color = ColorRGBA(r=0.85, g=0.85, b=0.85, a=1.0)
        for dy, dz in [(-148.5, -105), (148.5, -105), (148.5, 105), (-148.5, 105), (-148.5, -105)]:
            m.points.append(pt((c[0], c[1] + dy, c[2] + dz)))
        m.lifetime = Duration()
        return m

    def trail_marker(self):
        m = Marker(type=Marker.LINE_LIST, action=Marker.ADD, ns="trail", id=1)
        m.header.frame_id = "base_link"
        m.scale.x = 0.0015
        m.color = ColorRGBA(r=0.9, g=0.2, b=0.15, a=1.0)
        m.points = [pt(p) for seg in self.trail for p in seg]
        return m

    def pen_markers(self, p):
        """펜홀더+펜 막대(플랜지 -> 펜 끝)와 펜 끝 구."""
        pen = Marker(type=Marker.LINE_LIST, action=Marker.ADD, ns="pen", id=2)
        pen.header.frame_id = "base_link"
        pen.scale.x = 0.008
        pen.color = ColorRGBA(r=0.95, g=0.65, b=0.05, a=1.0)
        pen.points = [pt(p["tcp_mm"]), pt(self.tip(p))]
        nib = Marker(type=Marker.SPHERE, action=Marker.ADD, ns="pen", id=3)
        nib.header.frame_id = "base_link"
        nib.pose.position = pt(self.tip(p))
        nib.pose.orientation.w = 1.0
        nib.scale.x = nib.scale.y = nib.scale.z = 0.006
        down = p["pen_down"]
        nib.color = ColorRGBA(r=0.9, g=0.2, b=0.15, a=1.0) if down else ColorRGBA(r=0.3, g=0.3, b=0.3, a=1.0)
        return [pen, nib]

    def status_marker(self, text):
        """종이 위쪽에 상태 글자 (그리는 중 29% / 멈춤 / 완료 / 오류)."""
        c = self.tip(self.points[0])
        m = Marker(type=Marker.TEXT_VIEW_FACING, action=Marker.ADD, ns="status", id=4)
        m.header.frame_id = "base_link"
        m.pose.position = pt((c[0], c[1], c[2] + 118))
        m.pose.orientation.w = 1.0
        m.scale.z = 0.012
        m.color = ColorRGBA(r=0.1, g=0.1, b=0.1, a=1.0)
        m.text = text
        return m

    def publish(self, p, text=None):
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = self.traj["joint_names"]
        js.position = p["q"]
        self.js_pub.publish(js)
        markers = [self.paper_marker(), self.trail_marker(), *self.pen_markers(p)]
        if text is not None:
            markers.append(self.status_marker(text))
        ma = MarkerArray(markers=markers)
        for m in ma.markers:
            m.header.stamp = js.header.stamp
        self.mk_pub.publish(ma)

    def tick(self):
        if self.i >= len(self.points):
            if not self.loop:
                return
            self.i, self.trail = 0, []
        p = self.points[self.i]
        if self.i > 0 and p["pen_down"] and self.points[self.i - 1]["pen_down"]:
            self.trail.append((self.tip(self.points[self.i - 1]), self.tip(p)))
        self.publish(p)
        self.i += 1


class FollowPlayback(Playback):
    """진행 파일을 읽어 로봇의 명령 응답 위치를 따라감 (GUI '로봇으로 그리기')."""

    def __init__(self, traj, progress_path):
        from mirobot_sketch.live_progress import FollowTrack

        super().__init__(traj, speed=1.0, loop=False, start_timer=False)
        self.progress_path = progress_path
        self.run_id, self.shown = None, 0
        self.track = FollowTrack(self.points, traj.get("cmd_feed_mm_min", []), traj.get("step_mm", 1.0))
        self.timer = self.create_timer(FOLLOW_PERIOD_S, self.follow_tick)

    def reload(self, path):
        from mirobot_sketch.live_progress import FollowTrack, to_local_path

        with open(to_local_path(path), encoding="utf-8") as f:
            self.traj = json.load(f)
        self.points = self.traj["points"]
        self.track = FollowTrack(self.points, self.traj.get("cmd_feed_mm_min", []), self.traj.get("step_mm", 1.0))
        self.trail, self.shown = [], 0

    def follow_tick(self):
        from mirobot_sketch.live_progress import read_progress

        prog = read_progress(self.progress_path)
        if prog and prog.get("run_id") != self.run_id and prog.get("trajectory"):
            self.run_id = prog["run_id"]
            try:
                self.reload(prog["trajectory"])
            except (OSError, ValueError) as e:
                self.get_logger().warn(f"궤적을 읽지 못함: {e}")
        idx = self.track.index(prog, time.time())
        while self.shown < idx:                      # 지나온 펜다운 구간만 자국으로
            a, b = self.points[self.shown], self.points[self.shown + 1]
            if a["pen_down"] and b["pen_down"]:
                self.trail.append((self.tip(a), self.tip(b)))
            self.shown += 1
        self.publish(self.points[idx], self.status_text(prog))

    @staticmethod
    def status_text(prog):
        if not prog:
            return "waiting"
        st, a, n = prog.get("state"), prog.get("acked", 0), max(prog.get("total", 1), 1)
        return {"running": f"drawing {100 * a // n}%", "stopped": "stopped", "done": "done",
                "homing": "homing"}.get(st, f"error: {prog.get('message', '')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--speed", type=float, default=10.0, help="실제 펜다운 속도 대비 배속")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--follow", help="진행 파일 경로: 로봇 명령 응답을 실시간으로 따라감")
    args = ap.parse_args()
    with open(args.trajectory, encoding="utf-8") as f:
        traj = json.load(f)
    rclpy.init()
    node = FollowPlayback(traj, args.follow) if args.follow else Playback(traj, args.speed, args.loop)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
