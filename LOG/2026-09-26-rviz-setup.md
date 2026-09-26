# 2026-09-26 — RViz 3D 환경 설치 도우미 (WSL2 + ROS 2 Humble + Mirobot 모델)

## 문제
- **증상:** RViz 3D 보기와 실시간 따라가기는 WSL2 Ubuntu 22.04에 ROS 2 Humble과 WLKATA Mirobot 모델을 손으로 설치한 PC에서만 동작했습니다. 다른 PC에서는 버튼이 흐려지기만 했습니다.
- **목표:** 버튼 하나로 환경을 갖추게 합니다. 사용자가 할 일은 WSL이 없을 때의 관리자 승인과 재부팅뿐입니다.

## 해결 (사용자 선택: WSL부터 전부, GUI·명령줄·설치 프로그램 세 곳, 미리 만든 이미지가 기본이고 스크립트는 예비)
- **`packaging/wsl/setup_ros_env.sh`:** CI 이미지와 예비 설치가 같이 쓰고, 이미 된 단계는 건너뜁니다.
  1. ROS 2 Humble ros-base를 설치합니다.
  2. rviz2, robot-state-publisher, colcon, g++, git, Mesa를 설치합니다.
  3. WLKATA 저장소를 커밋 `c0a7ad4`로 받아 `wlkata_mirobot_description`만 빌드합니다. `textures` 폴더는 공식 저장소에 빠져 있어 보충합니다.
  4. `--image` 모드에서는 비밀번호 없는 sudo 사용자 `mirobot`과 `wsl.conf`의 기본 사용자를 설정하고 정리합니다.
- **`mirobot_sketch/rviz_setup.py`:** 세 단계(① WSL 기능, ② RViz 환경, ③ 동작 확인)를 매번 처음부터 확인합니다.
  - 릴리스 이미지를 `Range`로 이어받고, SHA256을 확인한 뒤 압축을 풀어 `wsl --import MirobotSketch-ROS`로 가져옵니다.
  - 가져오기 전에 디스크 공간 5GB를 확인합니다.
  - 관리자 명령은 `wsl --install --no-distribution` 하나뿐이고, 비밀번호는 다루지 않습니다.
- **RViz 실행:** 가장 먼저 `MirobotSketch-ROS`를 씁니다(없으면 기존에 설치된 배포판).
- **화면과 명령:**
  - GUI 창: 단계, 지금 할 일, 진행률, 설치/이어서 설치, WSL 설치(관리자), 직접 설치(예비), 제거, 로그
  - 명령줄: `mirobot setup-rviz`
  - 설치 프로그램: "RViz 3D 환경도 설치" 선택 항목. 앱을 지울 때 배포판도 지울지 묻고, 조용한 제거에서는 "아니요"입니다.
  - "RViz를 쓸 수 없음" 메시지에서 도우미를 열 수 있습니다.
- **릴리스 CI의 `wsl-image` 작업:**
  1. `ubuntu:22.04` 컨테이너에서 스크립트(`--image`)를 실행합니다.
  2. 사용자 `mirobot`으로 ROS·모델·robot_state_publisher를 확인합니다.
  3. `docker export`, `gzip -9`, SHA256을 거쳐 1900MB 이하인지 검사하고 릴리스에 올립니다.
- **저장소 이름 변경** (`OSS-2026` → `OSS-2026-Mirobot-Photo-Sketch`): 다운로드 주소, 배지, 설치 프로그램 URL을 바꿨습니다.

## 실제로 확인하며 찾은 문제
- **C++ 컴파일러 없음:** 빈 Ubuntu 22.04에서 모델 빌드가 실패했습니다(`No CMAKE_CXX_COMPILER`). CMake `project()`가 C++ 컴파일러를 찾기 때문이라 g++를 추가했습니다.
- **실패한 빌드를 완료로 오인:** 빌드가 실패해도 `install/<패키지>` 폴더가 남아서, 다시 실행하면 "모델 있음"으로 건너뛰었습니다. 빌드가 성공해야만 생기는 `package.xml`로 판단하게 바꿨습니다.
- **도커 이미지에 sudo 없음:** 도커 `ubuntu:22.04`에는 sudo와 `/etc/sudoers.d`가 없어 CI 이미지 작업이 실패했습니다. 이미지 모드에서 sudo를 설치하고 폴더를 만들게 했습니다. WSL 루트 파일에는 sudo가 있어서 로컬에서는 드러나지 않았습니다.
- **cp949 콘솔:** 한국어 Windows 콘솔(cp949)이 ✓ 기호를 못 찍어 명령줄이 죽었습니다. 다른 명령처럼 `safe_console()`을 쓰게 했습니다.

## 최종 검토 후 고친 것 (별도 검토 에이전트)
- **예비 경로 변경:** [직접 설치(예비)]가 사용자의 기존 `Ubuntu-22.04`에 설치하던 것을 바꿨습니다. 이제 Ubuntu 공식 루트 파일로 **전용 배포판**을 만들고 그 안에서 스크립트를 실행합니다(이 PC에서 확인한 방식과 같음). 기존 배포판을 건드리지 않고, sudo 비밀번호와 추가 관리자 승인도 필요 없습니다.
- **디스크 공간:** 받기 전에 여유 공간(8GB)을 확인합니다. 압축을 풀다 디스크가 가득 차면 "손상"이 아니라 "공간 부족"으로 알립니다. SHA256이 맞는 받은 파일은 다시 받지 않습니다.
- **이미 있는 배포판:** 등록은 됐지만 ROS 확인이 실패하는 경우, 다시 가져오지 않고 [다시 확인]·[직접 설치]·[제거]를 안내합니다.
- **설치 창:** 설치·제거가 도는 중에는 [다시 확인]이 버튼을 다시 켜지 않습니다(두 번 설치되거나 설치 중 제거되는 것을 막음).
- **RViz 캐시:** "RViz 없음" 결과를 기억하지 않습니다. 설치 뒤 앱을 다시 켜지 않아도 'RViz 3D로 보기'가 됩니다.
- **릴리스 순서:** 이미지 작업이 Windows 작업 뒤에 올리도록 바꿔, 같은 릴리스를 동시에 만드는 충돌을 막았습니다.

## 확인 (이 PC)
1. **이미지 만들기:** Ubuntu 22.04 공식 WSL 루트 파일(SHA256 확인)을 임시 배포판 `MirobotSketch-ROS-build`로 가져와 `setup_ros_env.sh --image`를 실행했습니다.
   - 처음 설치에 447초가 걸렸고, 위 두 문제를 고친 뒤 이어서 실행하니 `SETUP_OK`가 나왔습니다.
   - 기본 사용자 `mirobot`, `ros2 pkg prefix wlkata_mirobot_description`, WSLg 소켓을 모두 확인했습니다.
2. **내보내기와 압축:** `wsl --export`(88초)로 1,651MB가 나왔고, gzip -6(117초)으로 **544MB**가 됐습니다.
3. **도우미로 가져오기:** `rviz_setup.install(image=…, name="MirobotSketch-ROS-test")`로 압축 풀기와 가져오기에 74초가 걸렸고, 세 단계 모두 통과했습니다. 받은 파일은 지워졌습니다.
4. **따라가기:** `MIROBOT_WSL_DISTRO=MirobotSketch-ROS-test`로 illust1을 가상 시뮬레이션 20배속으로 그렸습니다.
   - `robot_state_publisher`, `rviz2`, `rviz_playback.py --follow`가 실행되고 `/sketch_markers`가 나오는 것을 확인했습니다(PASS).
5. **정리:** 임시 배포판 2개를 unregister하고 설치 폴더와 이미지를 지웠습니다. 기존 `Ubuntu`, `Ubuntu-22.04`는 그대로입니다.

- **릴리스 CI 수동 실행:**
  - windows 작업은 통과했습니다: exe에 설치 스크립트·얼굴 모델 포함, `mirobot setup-rviz --help`, 설치 프로그램 컴파일, 조용한 설치·제거.
  - wsl-image 작업은 첫 실행에서 실패했습니다(도커에 sudo 없음). 고친 뒤 다시 실행해 통과했습니다: `SETUP_OK`, 사용자 `mirobot`으로 ROS·모델·robot_state_publisher 확인, `default=mirobot`.
  - 이미지 크기는 **401MB**입니다(gzip -9). 로컬 WSL 내보내기보다 작습니다(도커 export에는 WSL 설정·캐시가 없음).
- **자동 테스트:** 전체 통과, pyflakes 깨끗

## 다음
- 다음 릴리스(v0.3.0) 태그에서 이미지가 릴리스에 올라가면, WSL이 없는 다른 PC에서 [WSL 설치(관리자)] → 재부팅 → [설치]까지 해 봐야 합니다.
