# Open Sourse Software - (2026-2)

- [O] Make a repositories
- [O] write README.md

---

## 텀프로젝트: Mirobot Photo Sketch

<img src="assets/app_icon_256.png" width="128" alt="앱 아이콘: 로봇 팔이 종이에 하트를 그리는 모습">

[![CI](https://github.com/yoobinkim541/OSS-2026/actions/workflows/ci.yml/badge.svg)](https://github.com/yoobinkim541/OSS-2026/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/yoobinkim541/OSS-2026)](https://github.com/yoobinkim541/OSS-2026/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

사진을 입력하면 OpenCV로 선 경로를 만들고, WLKATA Mirobot 로봇팔이 벽에 붙인 A4 용지에 펜으로 그리는 오픈소스프로그래밍 텀프로젝트입니다.

```
사진 ─▶ CV/make_strokes.py (또는 gui_sketch.py) ─▶ 획 JSON (종이 mm)
     ─▶ robot/draw_executor.py (dry-run → --execute) ─▶ Mirobot 펜 드로잉
```

### 설치

**Windows 사용자 (파이썬 없이):** [Releases](https://github.com/yoobinkim541/OSS-2026/releases)에서 `MirobotSketch-vX.Y.Z-windows-x64.zip`을 받아 압축을 풉니다.
- `MirobotSketch.exe`: GUI
- `mirobot.exe`: 명령줄 도구 (`mirobot draw …`, `mirobot strokes …`, `mirobot sim …`)

설정 파일은 처음 실행할 때 `%APPDATA%\MirobotSketch\drawing_config.json`에 만들어지고, 실행 기록은 같은 폴더의 `runs\`에 쌓입니다. 이 파일에서 포트와 보정값을 고칩니다. 배경 제거(rembg)는 용량 문제로 .exe에 넣지 않았습니다.

**개발자 (파이썬 3.10 이상):**

```bash
pip install -e .
```

`mirobot-sketch`(GUI), `mirobot-strokes`, `mirobot-draw`, `mirobot-sim` 명령이 생깁니다. 저장소에서 실행하면 `robot/drawing_config.json`, `LOG/runs/`, `out/`을 그대로 씁니다. 추가 기능은 필요할 때 설치합니다.
- 배경 제거: `pip install -e ".[rembg]"` (첫 실행 때 모델 약 170MB를 내려받음)
- .exe 빌드: `pip install -e ".[build]"` 후 `pyinstaller packaging/mirobot_sketch.spec --noconfirm`

### 사용법

#### 1. 사진 → 획 JSON

GUI (추천):

```bash
mirobot-sketch            # 또는 python CV/gui_sketch.py
```

CustomTkinter로 만든 카드형 화면이며 라이트/다크 모드를 지원합니다. 사진을 열고 이미지 종류(실사 사진 / 컬러 일러스트 / 흑백 만화)를 고르면 추천 설정이 들어갑니다. A4 종이 위에 실제 크기와 펜 굵기로 미리 보여 주고, 예상 시간(그리기·이동·펜 올림/내림·명령 지연)과 로봇 시뮬레이션(관절 한계 PASS/FAIL) 결과를 함께 표시합니다.

명령줄:

```bash
mirobot-strokes photo.jpg --type photo --out out/photo
```

- `--type photo|illustration|manga` : 이미지 종류별 추천 설정 (`CV/presets.py`)
- `--detail low|medium|high` : 상세도. 낮출수록 획 수와 그리는 시간이 줄어듭니다.
- `--rembg` / `--no-rembg` : 배경 제거 (결과는 `out/cache/`에 저장해 재사용)
- `--median 11` : 만화 스크린톤(망점)처럼 작은 무늬를 지웁니다.
- `--dedupe 4` : 펜 굵기보다 가까운 이중선(굵은 선의 양쪽 경계)을 하나로 (기본 4px, 0=끔)
- `--merge 4` : 끝점이 만나는 획을 이어 그려 펜 올림 횟수를 줄입니다 (기본 4px, 0=끔)
- `--lines dark` : 깨끗한 선화에서 어두운 선의 중심선을 그립니다.
- `--box W H` : 그리기 상자 크기(mm). 기본값은 100 × 100입니다.

`out/photo.json`과 비교 이미지 `out/photo_preview.png`(입력 / 선 후보 / 획 / 그리는 순서)가 만들어집니다.

#### 2. 획 JSON → 로봇

```bash
mirobot-draw out/photo.json
```

기본은 **dry-run**이라 로봇을 움직이지 않고 G-code 파일과 요약만 만듭니다. 실제로 그리기 전에 다음을 준비합니다.

1. 전원을 켜고 중앙 버튼을 2초 눌러 호밍한 뒤 Idle 상태를 확인합니다.
2. 펜 끝을 종이 중앙에 둡니다.
3. `robot/drawing_config.json`의 포트, 중심 TCP, 부호를 확인합니다.

준비가 끝나면 실행합니다.

```bash
mirobot-draw out/photo.json --execute
```

실행 결과는 `LOG/runs/`에 저장됩니다. 처음 실행할 때는 `trajectories/orientation-test-F.json`으로 좌우·상하 방향부터 확인하세요.

- `--air` : 펜을 종이에 대지 않고 같은 경로를 따라갑니다(도달 범위·충돌 확인용).
- `--pending-limits` : 실물 확인 전의 확장 범위(±60mm)로 검사합니다. 범위 확인 시험(`trajectories/border-test-60mm.json`)에만 씁니다.

그리기 범위를 ±50mm에서 ±60mm로 넓히는 절차는 `robot/drawing_config.json`의 `_limits_pending_note`를 따릅니다.

### 3D 시뮬레이션 (로봇 없이 확인)

실행기와 같은 경로로 Mirobot 기구학(IK)을 풀어 관절 한계(Soft limit)를 넘는지 검사합니다.

```bash
mirobot-sim out/photo.json --plot out/joints.png --gif out/sim.gif
mirobot-sim --reach-map out/reach_map.png
```

RViz에서 실제 Mirobot 3D 모델로 재생하려면 궤적을 내보낸 뒤 WSL2(ROS 2 Humble)에서 실행합니다.

```bash
mirobot-sim out/photo.json --export out/photo_traj.json
wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/asus/Desktop/Mirobot && bash sim/run_rviz.sh out/photo_traj.json 10"
```

### 배포 (CI/CD)

- **CI** (`.github/workflows/ci.yml`): main push와 PR마다 Windows/Ubuntu × Python 3.11/3.13에서 테스트와 명령줄 도구 동작을 확인합니다.
- **CD** (`.github/workflows/release.yml`): `v*` 태그를 push하면 Windows .exe를 빌드하고, 빌드된 exe로 동작을 확인한 뒤 GitHub Releases에 zip으로 올립니다.
- **Dependabot** (`.github/dependabot.yml`): Actions와 의존성 업데이트를 매주 PR로 알려 줍니다.

새 버전 배포:

```bash
git tag -a v0.2.0 -m "..." && git push origin v0.2.0
```

`mirobot_sketch/__init__.py`의 `__version__`도 함께 올립니다.

### 테스트

```bash
python -m unittest discover -s tests -v
```

### 폴더

| 경로 | 내용 |
|---|---|
| `mirobot_sketch/` | 파이썬 패키지: CV 파이프라인, 종이 좌표, 실행기, 시뮬레이터, GUI (`data/`에 기본 설정·아이콘) |
| `CV/` | 저장소용 실행 파일(`gui_sketch.py`, `make_strokes.py`), `experiments/`는 학습 단계 스크립트 |
| `robot/` | 로봇 설정(`drawing_config.json`), 저장소용 실행기 진입점, 초기 시리얼·그리퍼·펌프 시험 코드 |
| `sim/` | 저장소용 시뮬레이터 진입점, RViz 재생(WSL2 ROS 2) |
| `packaging/` | PyInstaller 빌드 설정과 .exe 진입점 |
| `.github/workflows/` | CI(테스트), Release(태그 push 시 .exe 빌드) |
| `assets/` | 앱 아이콘과 생성 스크립트 |
| `trajectories/` | 도형 템플릿과 테스트 경로 |
| `docs/` | 설계 문서, OpenCV 학습 자료 |
| `LOG/` | 날짜별 작업 기록, 실행 기록 |
| `tests/` | 회귀 테스트 |

### 라이선스

[MIT](LICENSE)

### 환경 메모

- 실물 제어는 Windows pyserial로 합니다. WSL2에 USB 패스스루한 CH340 포트는 응답을 읽지 못합니다.
- 시리얼 포트를 새로 열면 보드가 리셋됩니다. 실행 중에는 다른 프로그램이 같은 포트를 열지 않게 합니다.
- ROS 2 Humble / MoveIt 2(WSL2)는 경로 검토와 시각화에 사용합니다.
