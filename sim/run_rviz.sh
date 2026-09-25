#!/usr/bin/env bash
# RViz에서 Mirobot 3D 모델로 드로잉 궤적 재생 (WSL2 Ubuntu 22.04 + ROS 2 Humble)
#   Windows: python sim/mirobot_sim.py trajectories/orientation-test-F.json --export out/F_traj.json
#   WSL:     bash sim/run_rviz.sh out/F_traj.json [배속=10]
#   (GUI의 "RViz 3D로 보기" 버튼이 이 스크립트를 WSL에서 대신 실행함)
set -e
TRAJ="${1:?관절 궤적 JSON 경로가 필요합니다}"
SPEED="${2:-10}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# 이전에 띄운 재생·RViz가 남아 있으면 정리 (GUI에서 다시 열 때)
pkill -f rviz_playback.py 2>/dev/null || true
pkill -x rviz2 2>/dev/null || true
pkill -f "robot_state_publisher " 2>/dev/null || true
source /opt/ros/humble/setup.bash
source "$HOME/mirobot_ws/install/setup.bash"
URDF="$(ros2 pkg prefix wlkata_mirobot_description)/share/wlkata_mirobot_description/urdf/wlkata_mirobot_description.urdf"

ros2 run robot_state_publisher robot_state_publisher "$URDF" > /tmp/mirobot_rsp.log 2>&1 &
RSP=$!
# WSLg에서 GPU(OpenGL) 가속이 안 되면 RViz 창이 검게/안 보이게 뜸 ([WARN:COPY MODE]).
# 기본은 소프트웨어 렌더링. GPU를 쓰려면 MIROBOT_RVIZ_GPU=1 로 실행.
if [ "${MIROBOT_RVIZ_GPU:-0}" != "1" ]; then export LIBGL_ALWAYS_SOFTWARE=1; fi
rviz2 -d "$HERE/rviz/mirobot_sketch.rviz" > /tmp/mirobot_rviz.log 2>&1 &
RVIZ=$!
sleep 2
python3 "$HERE/rviz_playback.py" "$TRAJ" --speed "$SPEED" --loop &
PLAY=$!
trap 'kill $RSP $RVIZ $PLAY 2>/dev/null' EXIT
# RViz 창을 닫으면 재생·상태 발행도 함께 종료
wait $RVIZ || true
