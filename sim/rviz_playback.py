#!/usr/bin/env python3
"""
시뮬레이션 관절 궤적을 RViz의 Mirobot 3D 모델로 재생합니다 (WSL2 / ROS 2 Humble).

sim/mirobot_sim.py --export 로 만든 JSON을 읽어 /joint_states를 발행하고,
종이(A4 테두리)와 펜다운 궤적을 /sketch_markers로 표시합니다.
보통은 sim/run_rviz.sh 로 robot_state_publisher, rviz2와 함께 실행합니다.

    python3 sim/rviz_playback.py traj.json --speed 10 --loop
"""

import argparse
import json

import rclpy
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Point
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

REAL_FEED_MM_S = 300 / 60.0  # 펜다운 속도 300 mm/min 기준 1mm 샘플 = 0.2 s


def pt(mm):
    return Point(x=mm[0] / 1000.0, y=mm[1] / 1000.0, z=mm[2] / 1000.0)


class Playback(Node):
    def __init__(self, traj, speed, loop):
        super().__init__("sketch_playback")
        self.traj = traj
        self.points = traj["points"]
        self.loop = loop
        self.i = 0
        self.js_pub = self.create_publisher(JointState, "joint_states", 10)
        qos = QoSProfile(depth=5, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.mk_pub = self.create_publisher(MarkerArray, "sketch_markers", qos)
        self.trail = []
        period = (1.0 / REAL_FEED_MM_S) / speed
        self.timer = self.create_timer(period, self.tick)
        self.get_logger().info(f"{traj.get('source')}: {len(self.points)} samples, x{speed} speed")

    def paper_marker(self):
        c = self.points[0]["tcp_mm"]  # 시작점 = 종이 중심 (TCP 평면)
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

    def tick(self):
        if self.i >= len(self.points):
            if not self.loop:
                return
            self.i, self.trail = 0, []
        p = self.points[self.i]
        if self.i > 0 and p["pen_down"] and self.points[self.i - 1]["pen_down"]:
            self.trail.append((self.points[self.i - 1]["tcp_mm"], p["tcp_mm"]))
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = self.traj["joint_names"]
        js.position = p["q"]
        self.js_pub.publish(js)
        ma = MarkerArray(markers=[self.paper_marker(), self.trail_marker()])
        for m in ma.markers:
            m.header.stamp = js.header.stamp
        self.mk_pub.publish(ma)
        self.i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trajectory")
    ap.add_argument("--speed", type=float, default=10.0, help="실제 펜다운 속도 대비 배속")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    with open(args.trajectory, encoding="utf-8") as f:
        traj = json.load(f)
    rclpy.init()
    node = Playback(traj, args.speed, args.loop)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
