#!/usr/bin/env bash
# RViz에서 Mirobot 3D 모델로 드로잉 궤적 재생 (WSL2 Ubuntu 22.04 + ROS 2 Humble)
#   Windows: python sim/mirobot_sim.py trajectories/orientation-test-F.json --export out/F_traj.json
#   WSL:     bash sim/run_rviz.sh out/F_traj.json [배속=10]
set -e
TRAJ="${1:?관절 궤적 JSON 경로가 필요합니다}"
SPEED="${2:-10}"
HERE="$(cd "$(dirname "$0")" && pwd)"
source /opt/ros/humble/setup.bash
source "$HOME/mirobot_ws/install/setup.bash"
URDF="$(ros2 pkg prefix wlkata_mirobot_description)/share/wlkata_mirobot_description/urdf/wlkata_mirobot_description.urdf"

ros2 run robot_state_publisher robot_state_publisher "$URDF" > /tmp/mirobot_rsp.log 2>&1 &
RSP=$!
rviz2 -d "$HERE/rviz/mirobot_sketch.rviz" > /tmp/mirobot_rviz.log 2>&1 &
RVIZ=$!
trap 'kill $RSP $RVIZ 2>/dev/null' EXIT
sleep 2
python3 "$HERE/rviz_playback.py" "$TRAJ" --speed "$SPEED" --loop
