# RViz 3D 환경 설치 도우미 (WSL + ROS 2 Humble + Mirobot 모델)

설계 문서 · 2026-09-26

## 1. 배경과 목표

- **지금 상태:** RViz 3D 보기와 실시간 따라가기는 WSL2 + Ubuntu 22.04 + ROS 2 Humble + WLKATA Mirobot 모델이 **손으로 설치된 PC**에서만 됩니다. 다른 PC에서는 버튼이 흐려질 뿐입니다.
- **목표:** 사용자가 버튼 하나로 RViz 환경을 갖추게 합니다. 사용자가 할 일은 WSL이 없을 때의 관리자 승인과 재부팅뿐이어야 합니다.

### 사용자가 정한 것
- WSL 기능부터 전부 설치합니다.
- 시작 위치: GUI 버튼, 명령줄(`mirobot setup-rviz`), 설치 프로그램 선택 항목
- 방식은 **미리 만든 이미지를 가져오기(C)가 기본**이고, 설치 스크립트(A)는 예비입니다. 이미지는 릴리스 CI가 같은 스크립트로 만듭니다.

### 성공 기준
- WSL이 이미 있는 PC에서 [설치] 한 번이면, 사용자 입력 없이 `MirobotSketch-ROS` 배포판이 생기고 RViz 따라가기가 동작합니다.
- 중간에 끊기거나 재부팅한 뒤 다시 누르면, 끝난 단계는 건너뛰고 받던 파일도 이어받습니다.
- 사용자 PC의 기존 WSL 배포판은 건드리지 않습니다.
- 비밀번호를 다루지 않습니다. 관리자 명령은 `wsl --install --no-distribution` 하나뿐입니다.

## 2. 단계

| 단계 | 확인 | 없으면 | 사용자 |
|---|---|---|---|
| ① WSL 기능 | `wsl --status` 성공 | 관리자 창: `wsl --install --no-distribution` | 승인 → 재부팅 |
| ② RViz 환경 | 배포판 `MirobotSketch-ROS`가 있고 ROS·모델 확인 통과 | 이미지 다운로드(이어받기) → SHA256 → 압축 풀기 → `wsl --import` | 없음 |
| ③ 동작 확인 | `ros2 pkg prefix wlkata_mirobot_description` 성공, WSLg 소켓(`/tmp/.X11-unix/X0`) 있음 | 원인과 해결 방법 표시 | 없음 |

- **확인 방식:** 매번 세 단계를 처음부터 확인하고, 끝난 단계는 건너뜁니다(별도 상태 파일 없음).
- **저장 위치:** `%LOCALAPPDATA%\MirobotSketch\wsl\`
  - 받는 중인 파일: `*.part`
  - 배포판 디스크: `MirobotSketch-ROS\`
  - 받은 압축 파일은 가져온 뒤 지웁니다.
- **RViz 실행:** `MirobotSketch-ROS`를 가장 먼저 찾습니다. 없으면 ROS가 있는 다른 배포판을 씁니다(기존 설치 호환). `MIROBOT_WSL_DISTRO`로 지정하면 그것을 씁니다.
- **예비 경로 [직접 설치]:** `Ubuntu-22.04` 배포판이 없으면 `wsl --install -d Ubuntu-22.04`로 만들고(사용자 계정은 사용자가 직접 만듦), 새 콘솔에서 `setup_ros_env.sh`를 실행합니다. `sudo` 비밀번호는 사용자가 콘솔에 직접 입력합니다.
- **제거:** `wsl --unregister MirobotSketch-ROS`. 앱을 제거할 때도 함께 지울지 묻습니다.

## 3. 이미지와 설치 스크립트

- **`packaging/wsl/setup_ros_env.sh`:** CI 이미지와 예비 설치가 같이 씁니다. 이미 된 부분은 건너뜁니다.
  1. 로캘 설정, `universe` 저장소, ROS 2 apt 키와 저장소 등록 → `ros-humble-ros-base`
  2. `ros-humble-rviz2`, `ros-humble-robot-state-publisher`, `python3-colcon-common-extensions`, git, Mesa(소프트웨어 렌더링)
  3. 사용자 `mirobot`: 비밀번호 없는 sudo, `/etc/wsl.conf`의 `[user] default=mirobot`
     - 이미지를 만들 때만 합니다. 예비 설치는 현재 사용자를 씁니다.
  4. `~/mirobot_ws/src`에 `https://github.com/wlkata/Wlkata_Mirobot_Ros2`를 커밋 `c0a7ad4`로 받습니다. `wlkata_mirobot_description/textures`를 만들고 `colcon build --packages-select wlkata_mirobot_description`을 실행합니다.
  5. 정리: apt 캐시, colcon `build/`와 `log/`
- **CI (`release.yml`의 `wsl-image` 작업, Ubuntu 서버)**
  1. `docker run ubuntu:22.04`로 스크립트를 실행하고 확인합니다(ROS·모델, `robot_state_publisher` 실행 파일).
  2. `docker export` → `gzip -9` → `MirobotSketch-ROS-humble-<버전>.tar.gz`와 `.sha256`
  3. 1.9GB를 넘으면 실패시킵니다. 통과하면 릴리스에 올립니다.
- **다운로드 주소:** `https://github.com/yoobinkim541/OSS-2026/releases/download/v<버전>/MirobotSketch-ROS-humble-<버전>.tar.gz`
  - 그 버전의 이미지가 없으면, GitHub API로 이미지가 있는 최신 릴리스를 찾습니다.

## 4. 화면과 명령

- **GUI:** "③ 실행" 카드의 [RViz 3D 환경…] 버튼으로 창을 엽니다.
  - 단계 표시(✓ ● ✕ ○), 진행률, "지금 할 일"을 보여 줍니다.
  - 버튼: [설치 / 이어서 설치], [직접 설치(예비)], [제거], [로그 열기], [닫기]
  - RViz를 쓸 수 없다는 메시지에도 이 창을 여는 안내를 붙입니다.
- **명령줄:** `mirobot setup-rviz --check | --install | --uninstall | --manual`
  - `--check`의 종료 코드: 0이면 준비 완료, 1이면 부족함
- **GUI 실행 인자:** `MirobotSketch.exe --setup-rviz`는 창을 띄운 뒤 도우미를 바로 엽니다.
- **설치 프로그램:** 선택 작업 "RViz 3D 환경도 설치(약 1GB 다운로드)"를 체크하면, 설치 후 `--setup-rviz`로 실행합니다. 앱을 제거할 때는 배포판도 지울지 묻습니다.

## 5. 실패 처리와 보안

- **실패 표시:** 단계마다 원인과 해결 방법을 보여 줍니다.
  - 가상화가 꺼져 있음(`0x80370102` 등)
  - 디스크 공간 부족(가져오기 전에 5GB 확인)
  - 다운로드 실패
  - SHA256 불일치
- **예비 경로 권유:** 다운로드가 3번 실패하거나 SHA256이 맞지 않으면 [직접 설치]를 권합니다.
- **로그:** `rviz_setup.log`(사용자 폴더)에 남깁니다.

## 6. 테스트와 확인

- **단위 테스트 (가짜 WSL과 HTTP):**
  - 단계 판정
  - 배포판 선택 순서
  - 이어받기(Range) 요청
  - SHA256 거부
  - 압축 풀기
  - 명령줄 종료 코드
  - 관리자 명령 구성
- **CI:** 이미지 빌드, 컨테이너 안에서 확인, 크기 검사
- **이 PC에서 직접 확인:**
  1. Ubuntu 22.04 공식 WSL 루트 파일을 임시 배포판으로 가져옵니다.
  2. `setup_ros_env.sh --image`를 실행합니다(예비 경로 검증 겸용).
  3. 내보낸 뒤 `MirobotSketch-ROS-test`로 가져옵니다.
  4. `MIROBOT_WSL_DISTRO`로 그 배포판을 지정해 가상 시뮬레이션 드로잉과 RViz 따라가기를 확인합니다.
  5. 임시 배포판을 모두 지웁니다. 기존 `Ubuntu-22.04`는 건드리지 않습니다.
