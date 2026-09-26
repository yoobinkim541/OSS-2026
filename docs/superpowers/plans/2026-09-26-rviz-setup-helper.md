# RViz 3D 환경 설치 도우미 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 버튼 하나로 WSL 기능 → 전용 배포판 `MirobotSketch-ROS`(ROS 2 Humble + Mirobot 모델) → 동작 확인까지 설치해 RViz 3D·실시간 따라가기를 쓸 수 있게 한다.

**Architecture:**
- **`rviz_setup.py`:** 단계 확인과 설치를 맡는다. 확인은 가짜 `run`으로 테스트하고, 다운로드는 가짜 HTTP로 테스트한다.
- **`packaging/wsl/setup_ros_env.sh`:** CI 이미지 만들기와 예비 설치가 같이 쓴다.
- **화면:** GUI 창(`rviz_setup_window.py`), 명령줄 `mirobot setup-rviz`, 설치 프로그램 선택 작업이 모두 `rviz_setup`을 부른다.
- **이미지:** 릴리스 CI가 `ubuntu:22.04` 컨테이너에서 만든다.

**Tech Stack:** Python 3.11+, requests, WSL 2, bash, GitHub Actions(docker), Inno Setup 6, CustomTkinter

**Spec:** `docs/superpowers/specs/2026-09-26-rviz-setup-helper-design.md`

## Global Constraints
- **배포판과 저장소:**
  - 배포판 이름은 `MirobotSketch-ROS`, 설치 폴더는 `%LOCALAPPDATA%\MirobotSketch\wsl\`
  - 이미지 파일은 `MirobotSketch-ROS-humble-<버전>.tar.gz`와 `.sha256`
  - WLKATA 저장소는 `https://github.com/wlkata/Wlkata_Mirobot_Ros2`의 커밋 `c0a7ad4`
- **권한과 비밀번호:** 관리자 명령은 `wsl --install --no-distribution` 하나뿐이다. 비밀번호를 받거나 저장하지 않는다.
- **기존 배포판:** 사용자 PC의 기존 WSL 배포판을 수정하거나 지우지 않는다. 지우는 것은 `MirobotSketch-ROS`와 테스트용 배포판뿐이다.
- **테스트:** `python -m unittest discover -s tests`가 전부 통과하고 pyflakes가 깨끗해야 한다. 실제 WSL과 네트워크는 테스트에서 부르지 않는다(가짜 사용).
- **커밋:** 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. 브랜치는 `feature/rviz-setup`이다.

## Review Focus
1. **다운로드가 중간에 끊긴 뒤 다시 설치:** `Range` 헤더로 이어받아야 하고, 서버가 `Range`를 무시하고 200을 주면 처음부터 받아야 한다(파일이 두 배로 붙으면 안 됨). → Task 2
2. **SHA256 불일치나 손상된 gz:** 가져오기 전에 거부하고, 받은 파일을 지워 다음에는 새로 받게 한다. → Task 2
3. **디스크 공간 부족:** 가져오기 전에 5GB를 확인하고 알린다. → Task 2
4. **WSL 명령 출력이 UTF-16:** `wsl -l -q`, `wsl --status` 출력 해석이 깨지지 않아야 한다. → Task 2(기존 `list_distros` 재사용)
5. **이미 `MirobotSketch-ROS`가 있는데 [설치]:** 가져오기를 다시 하지 않고 ③만 확인한다. → Task 2

---

### Task 1: 설치 스크립트 `packaging/wsl/setup_ros_env.sh`

**Files:** Create `packaging/wsl/setup_ros_env.sh`; Test `tests/test_rviz_setup.py` (정적 검사)

**Interfaces:**
- `bash setup_ros_env.sh [--image]`
  - `--image`: 이미지 만들기용. 사용자 `mirobot`을 만들고 `wsl.conf`를 설정한 뒤 정리까지 한다. root로 실행한다.
  - 인자가 없으면 예비 설치: 현재 사용자로 실행하고, 필요한 곳에만 `sudo`를 쓴다.
- 이미 된 단계는 건너뛴다: `/opt/ros/humble` 있음, 패키지 설치됨, `~/mirobot_ws/install/wlkata_mirobot_description` 있음.
- 마지막 줄은 `SETUP_OK`다.

- [ ] Step 1: 실패 테스트 — 스크립트가 있는지, LF 줄바꿈인지, `c0a7ad4`와 `--packages-select wlkata_mirobot_description`, `textures`, `set -euo pipefail`을 포함하는지, `bash -n` 문법 검사가 통과하는지(WSL이 있으면 `wsl bash -n`, 없으면 건너뜀). 실행 → FAIL
- [ ] Step 2: 스크립트를 작성한다. 순서는 다음과 같다.
  1. root 여부로 `SUDO=""` 또는 `SUDO=sudo`를 정한다.
  2. `DEBIAN_FRONTEND=noninteractive`로 locales와 `universe`를 설정한다.
  3. ROS 키(`/usr/share/keyrings/ros-archive-keyring.gpg`)와 저장소 목록을 등록하고 `ros-humble-ros-base`를 설치한다.
  4. rviz2, robot-state-publisher, colcon, git, `libgl1-mesa-dri`를 설치한다.
  5. `--image`일 때만: `useradd -m -s /bin/bash mirobot`, `/etc/sudoers.d/mirobot`(NOPASSWD), `/etc/wsl.conf`의 `[user] default=mirobot`, 대상 사용자를 mirobot으로 한다.
  6. 대상 사용자로 저장소를 받고 체크아웃한 뒤 `mkdir textures`, `source /opt/ros/humble/setup.bash && colcon build --packages-select wlkata_mirobot_description`을 실행한다.
  7. `--image`일 때: apt 캐시, `build/`, `log/`, `/.dockerenv`를 지운다.
  8. `echo SETUP_OK`
- [ ] Step 3: 테스트 통과 → 커밋

### Task 2: `mirobot_sketch/rviz_setup.py` — 확인·다운로드·가져오기·제거

**Files:** Create `mirobot_sketch/rviz_setup.py`; Test `tests/test_rviz_setup.py`

**Interfaces:**
- 상수: `DISTRO = "MirobotSketch-ROS"`, `IMAGE_NAME = "MirobotSketch-ROS-humble-{version}.tar.gz"`, `REPO = "yoobinkim541/OSS-2026"`, `MIN_FREE_BYTES = 5 * 2**30`
- `install_dir() -> Path`: `%LOCALAPPDATA%\MirobotSketch\wsl`, 없으면 `paths.user_dir()/wsl`
- `SetupStep(id, label, ok, detail, hint)`
- `check(run=subprocess.run) -> [SetupStep × 3]` (`wsl`, `env`, `verify`)
- `image_urls(version, get=requests.get) -> (url, sha_url)`: 그 버전의 릴리스를 먼저 쓰고, 없으면 API로 이미지가 있는 최신 릴리스를 쓴다.
- `download(url, dest, progress=None, should_cancel=None, get=requests.get) -> Path`: `dest.part`로 이어받는다. 206이면 이어 붙이고, 200이면 처음부터 쓴다. 끝나면 `dest`로 이름을 바꾼다.
- `verify_sha256(path, expected) -> bool`
- `gunzip(src, dst, progress=None)`: 스트리밍으로 풀고, 손상되면 `SetupError`를 낸다.
- `import_distro(tar_path, run=...)`: 디스크 공간을 확인하고 `wsl --import DISTRO <dir> <tar> --version 2`를 실행한다.
- `install(progress, should_cancel, run, get, version) -> [SetupStep]`: ①이 없으면 `SetupError("wsl")`을 낸다(화면이 관리자 설치를 안내). ②를 설치하고 ③을 확인한다.
- `install_wsl_feature(popen=...)`: PowerShell `Start-Process wsl -ArgumentList '--install','--no-distribution' -Verb RunAs`
- `manual_install(popen=...)`: `Ubuntu-22.04`가 없으면 `wsl --install -d Ubuntu-22.04`를 새 콘솔에서 실행하고, 있으면 그 배포판에서 `bash <스크립트>`를 새 콘솔에서 실행한다.
- `uninstall(run=...)`: `wsl --unregister DISTRO`
- `SetupError(step, message, hint)`

- [ ] Step 1: 실패 테스트
  - 가짜 `run`으로 확인:
    - WSL 없음(`FileNotFoundError`/status 실패) → ①만 실패
    - 배포판 없음 → ②가 실패하고 ③은 건너뜀
    - 모두 있음 → 셋 다 통과
  - 가짜 `get`으로 확인:
    - 이어받기: `.part`가 있으면 `Range: bytes=N-`를 보내고, 206이면 이어 붙이고, 200이면 처음부터 쓴다.
    - 멈춤 신호가 오면 `SetupError`를 내고 `.part`를 남긴다.
  - SHA256 불일치가 나면 파일을 지우고 `SetupError`를 낸다.
  - 손상된 gz면 `SetupError`를 낸다.
  - 디스크 공간이 부족하면(가짜 `shutil.disk_usage`) `SetupError`를 낸다.
  - 이미 있는 배포판이면 `install`이 다운로드를 부르지 않는다.
  - 관리자 명령과 예비 설치 명령의 구성을 확인한다.
  - 실행 → FAIL
- [ ] Step 2: 구현. WSL 출력은 `rviz_launch.list_distros`처럼 UTF-16을 풀어서 읽는다. ③의 확인 명령: `wsl -d DISTRO -- bash -lc 'source /opt/ros/humble/setup.bash && source ~/mirobot_ws/install/setup.bash && ros2 pkg prefix wlkata_mirobot_description && test -S /tmp/.X11-unix/X0'`
- [ ] Step 3: 통과 → 커밋

### Task 3: RViz 실행이 전용 배포판을 먼저 쓰기

**Files:** Modify `mirobot_sketch/rviz_launch.py`; Test `tests/test_rviz_launch.py`

- `find_ros_distro`의 우선순위: `MIROBOT_WSL_DISTRO` → `MirobotSketch-ROS` → 이름에 22.04가 든 배포판 → 나머지 배포판
- `SETUP_HINT` 끝에 "→ 'RViz 3D 환경…' 버튼(또는 mirobot setup-rviz)으로 자동 설치할 수 있습니다"를 붙인다.
- [ ] 실패 테스트(가짜 목록에 `Ubuntu-22.04`와 `MirobotSketch-ROS`가 둘 다 ROS 확인을 통과할 때 전용 배포판을 고르는지) → 구현 → 통과 → 커밋

### Task 4: 명령줄과 GUI

**Files:** Create `mirobot_sketch/rviz_setup_window.py`; Modify `mirobot_sketch/rviz_setup.py`(`main`), `packaging/launch_cli.py`, `pyproject.toml`(스크립트 `mirobot-setup-rviz`), `mirobot_sketch/gui.py`; Test `tests/test_rviz_setup.py`, `tests/test_gui_smoke.py`

- **`rviz_setup.main(argv)`:** `--check`(상태 출력, 준비되면 0), `--install`, `--uninstall`, `--manual`
- **`launch_cli`:** `setup-rviz` 명령
- **`RvizSetupWindow(app, font)`:** 단계 표시, 진행 막대, 지금 할 일, 버튼(설치 / 직접 설치 / 제거 / 로그 열기 / 닫기)
  - 설치는 작업 스레드에서 돌고, 화면은 `app.ui`로 갱신한다.
  - ① 실패 시: "관리자 승인 후 재부팅 → [이어서 설치]" 안내와 [WSL 설치(관리자)] 버튼
- **`gui.py`:** "③ 실행" 카드에 [RViz 3D 환경…] 버튼을 추가하고, `main()`에서 `--setup-rviz` 인자를 받으면 창을 연다.
- [ ] 실패 테스트:
  - 명령줄 `--check`의 종료 코드(가짜 `check`)
  - GUI 스모크: 창을 열었을 때 가짜 `check` 결과(①✓ ②✕ ③○)가 표시되는지, [설치]가 가짜 `install`을 부르는지
  - 실행 → FAIL
- [ ] 구현 → 통과 → 커밋

### Task 5: 릴리스 CI 이미지 작업과 설치 프로그램

**Files:** Modify `.github/workflows/release.yml`, `packaging/installer.iss`, `packaging/mirobot_sketch.spec`; Test `tests/test_rviz_setup.py`(정적 검사)

- **`release.yml`:** 새 작업 `wsl-image`를 추가한다(`runs-on: ubuntu-latest`).
  1. 체크아웃하고 `docker run --name rosimg ubuntu:22.04 bash /work/packaging/wsl/setup_ros_env.sh --image`를 실행한다(`-v $PWD:/work:ro`).
  2. 로그에 `SETUP_OK`가 있는지 확인한다.
  3. `docker commit` 후 확인한다: `docker run --rm -u mirobot img bash -lc 'source …; ros2 pkg prefix wlkata_mirobot_description && ls /opt/ros/humble/lib/robot_state_publisher/robot_state_publisher'`
  4. `docker export rosimg | gzip -9 > MirobotSketch-ROS-humble-$VER.tar.gz`, `sha256sum`, 크기가 1.9GB 이하인지 검사
  5. 태그면 릴리스에 올린다(기존 windows 작업과 같은 릴리스). 버전은 태그에서 `v`를 뗀 값이다.
- **`installer.iss`**
  - `[Tasks]`에 `rvizenv`("RViz 3D 환경도 설치 (약 1GB 다운로드)", 기본 해제)
  - `[Run]`에 `{app}\MirobotSketch.exe --setup-rviz`(Tasks: rvizenv, nowait postinstall)
  - `[Code]`의 `CurUninstallStepChanged`: `wsl -l -q`에 `MirobotSketch-ROS`가 있으면 지울지 묻고, 예면 `wsl --unregister`
- **spec datas:** `packaging/wsl/setup_ros_env.sh` → `wsl/`(예비 설치가 exe 안에서 스크립트를 찾도록). `rviz_setup.script_path()`는 저장소면 `packaging/wsl/`, 설치판이면 `_internal/wsl/`을 돌려준다.
- [ ] 실패 정적 테스트(`release.yml`에 `wsl-image`, `setup_ros_env.sh --image`, 1.9GB 검사 / `installer.iss`에 `rvizenv`, `--setup-rviz`, `--unregister` / `script_path()` 존재) → 구현 → 통과 → 커밋

### Task 6: 이 PC에서 처음부터 끝까지 확인과 기록

- [ ] 받은 Ubuntu 22.04 루트 파일(SHA256 확인)을 `MirobotSketch-ROS-build`로 가져온 뒤, root로 `bash /mnt/c/.../packaging/wsl/setup_ros_env.sh --image`를 실행한다 → `SETUP_OK`
- [ ] `wsl --export MirobotSketch-ROS-build img.tar` → `gzip` → SHA256 → 로컬 파일 주소로 `rviz_setup`의 확인·압축 풀기·가져오기 함수를 써서 `MirobotSketch-ROS-test`로 가져온다(가져올 배포판 이름을 인자로 받게 함) → `check` 통과 확인
- [ ] `MIROBOT_WSL_DISTRO=MirobotSketch-ROS-test`로 가상 시뮬레이션 20배속 드로잉과 RViz 따라가기를 실행해, WSL 프로세스와 `/sketch_markers`를 확인한다
- [ ] 두 임시 배포판을 unregister하고, 설치 폴더와 이미지 파일을 지운다
- [ ] 이미지 크기·설치 시간·결과를 LOG에 기록하고, README에 "RViz 3D 환경 설치"를 적는다 → 커밋
