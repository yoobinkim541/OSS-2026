#!/usr/bin/env bash
# Mirobot Sketch RViz 3D 환경: Ubuntu 22.04 위에 ROS 2 Humble(RViz에 필요한 최소) + WLKATA Mirobot 모델
#
#   bash setup_ros_env.sh --image   # 이미지 만들기 (root, CI의 ubuntu:22.04 컨테이너 / 임시 WSL 배포판)
#                                   #  -> 사용자 mirobot(비밀번호 없는 sudo), /etc/wsl.conf 기본 사용자, 정리까지
#   bash setup_ros_env.sh           # 직접 설치(예비): 현재 사용자로, 필요한 곳만 sudo (비밀번호는 사용자가 입력)
#
# 이미 된 단계는 건너뜁니다. 마지막 줄에 SETUP_OK를 출력합니다.
set -euo pipefail

IMAGE=0
[ "${1:-}" = "--image" ] && IMAGE=1
WLKATA_REPO="https://github.com/wlkata/Wlkata_Mirobot_Ros2.git"
WLKATA_COMMIT="c0a7ad4"          # 이 커밋에서 확인됨 (description 패키지에 textures 폴더만 보충하면 빌드됨)
export DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
if [ "$IMAGE" -eq 1 ] && [ -n "$SUDO" ]; then
  echo "--image는 root로 실행해야 합니다" >&2
  exit 2
fi
log() { echo "[setup] $*"; }
installed() { dpkg -s "$1" >/dev/null 2>&1; }

. /etc/os-release
if [ "${UBUNTU_CODENAME:-}" != "jammy" ]; then
  echo "ROS 2 Humble은 Ubuntu 22.04(jammy)용입니다. 지금: ${PRETTY_NAME:-알 수 없음}" >&2
  exit 3
fi

# 1) ROS 2 Humble 저장소와 기본 패키지
if ! installed ros-humble-ros-base; then
  log "ROS 2 apt 저장소 등록"
  $SUDO apt-get update
  $SUDO apt-get install -y --no-install-recommends locales software-properties-common curl gnupg2 ca-certificates
  $SUDO locale-gen en_US en_US.UTF-8
  $SUDO update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
  $SUDO add-apt-repository -y universe
  curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    | $SUDO tee /usr/share/keyrings/ros-archive-keyring.gpg >/dev/null
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu ${UBUNTU_CODENAME} main" | $SUDO tee /etc/apt/sources.list.d/ros2.list >/dev/null
  $SUDO apt-get update
  log "ros-humble-ros-base 설치"
  $SUDO apt-get install -y ros-humble-ros-base
else
  log "ROS 2 Humble 있음 — 건너뜀"
fi

# 2) RViz와 모델 빌드에 필요한 것 (소프트웨어 렌더링용 Mesa 포함)
PKGS="ros-humble-rviz2 ros-humble-robot-state-publisher python3-colcon-common-extensions git libgl1-mesa-dri"
MISSING=""
for p in $PKGS; do installed "$p" || MISSING="$MISSING $p"; done
if [ -n "$MISSING" ]; then
  log "설치:$MISSING"
  $SUDO apt-get update
  $SUDO apt-get install -y $MISSING
else
  log "RViz 패키지 있음 — 건너뜀"
fi

# 3) 이미지용 사용자 (WSL로 가져오면 이 사용자로 시작)
TARGET_USER="$(id -un)"
if [ "$IMAGE" -eq 1 ]; then
  id mirobot >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo mirobot
  echo "mirobot ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/mirobot
  chmod 0440 /etc/sudoers.d/mirobot
  printf '[user]\ndefault=mirobot\n\n[boot]\nsystemd=false\n' > /etc/wsl.conf
  TARGET_USER="mirobot"
fi

# 4) WLKATA Mirobot 모델 (description 패키지만 빌드: RViz에는 URDF와 메시만 필요)
build_model() {
  set -euo pipefail
  WS="$HOME/mirobot_ws"
  if [ -d "$WS/install/wlkata_mirobot_description" ]; then
    echo "[setup] Mirobot 모델 있음 — 건너뜀"
    return 0
  fi
  mkdir -p "$WS/src"
  if [ ! -d "$WS/src/Wlkata_Mirobot_Ros2/.git" ]; then
    git clone --quiet "$1" "$WS/src/Wlkata_Mirobot_Ros2"
  fi
  git -C "$WS/src/Wlkata_Mirobot_Ros2" -c advice.detachedHead=false checkout --quiet "$2"
  mkdir -p "$WS/src/Wlkata_Mirobot_Ros2/wlkata_mirobot_description/textures"   # 공식 저장소에 빠진 폴더
  cd "$WS"
  set +u                                    # ROS setup.bash는 정의 안 된 변수를 씀
  source /opt/ros/humble/setup.bash
  set -u
  colcon build --packages-select wlkata_mirobot_description
}
if [ "$TARGET_USER" = "$(id -un)" ]; then
  build_model "$WLKATA_REPO" "$WLKATA_COMMIT"
else
  runuser -u "$TARGET_USER" -- bash -c "$(declare -f build_model); build_model '$WLKATA_REPO' '$WLKATA_COMMIT'"
fi

# 5) 이미지 크기 줄이기
if [ "$IMAGE" -eq 1 ]; then
  apt-get clean
  rm -rf /var/lib/apt/lists/* /root/.cache /home/mirobot/.cache \
         /home/mirobot/mirobot_ws/build /home/mirobot/mirobot_ws/log /.dockerenv
fi

echo "SETUP_OK"
