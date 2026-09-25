# 2026-09-25 — 패키지화, Windows .exe, GitHub Actions

사용자 질문: ".exe도 만들고, 어떤 PC에서도 똑같이 동작하게 도커나 패키징을 해야 하지 않나? UI 라이브러리는 뭐가 있고, 실제 제품에서는 뭘 쓰나?"

## 결정

**도커는 이 앱에는 쓰지 않습니다.**
- 이 앱은 GUI 창과 USB 시리얼(CH340)을 씁니다. Windows 도커는 가상 머신 위에서 돌아서 둘 다 추가 설정(WSLg/X 서버, usbipd)이 필요합니다.
- 이미 WSL2에서 CH340 응답을 읽지 못하는 문제를 겪었는데, 도커는 그 위에 한 겹을 더 얹는 셈입니다.
- 도커가 맞는 곳은 ROS 2 Humble/MoveIt 환경 재현과 CI입니다. ROS 2 쪽은 선택 과제로 남겼습니다.

**배포 방식 (사용자 동의).**
1. `pyproject.toml` 패키지화
2. PyInstaller로 Windows .exe 빌드
3. GitHub Actions로 CI 테스트와 태그 기반 릴리스

**UI는 CustomTkinter를 유지합니다.** 실제 제품에서 Python 데스크톱은 주로 Qt(PySide6)를 쓰고, RViz와 rqt도 Qt입니다. 새로 만드는 일반 앱은 웹 기술(Electron/Tauri)이 흔합니다. 하지만 텀프로젝트의 평가 중심은 CV와 로봇 파이프라인이므로, UI를 다시 쓰기보다 배포와 재현성을 갖추는 쪽을 택했습니다.

## 1. 패키지 구조

**정의.** 기존 코드는 `CV/`, `robot/`, `sim/`의 스크립트가 `sys.path.insert`로 서로를 불러오는 구조였습니다. 이런 구조는 `pip install`이나 .exe로 만들면 경로가 깨집니다.

**해결.**
- 공용 코드를 `mirobot_sketch/` 패키지로 옮기고(`git mv`로 기록 유지), 패키지 안에서는 상대 import를 씁니다. `CV/gui_sketch.py`는 `mirobot_sketch/gui.py`가 됐습니다.
- 기존 명령(`python CV/make_strokes.py`, `python robot/draw_executor.py`, `python sim/mirobot_sim.py`, `python CV/gui_sketch.py`)은 원래 위치의 얇은 진입 파일로 그대로 쓸 수 있습니다.
- `mirobot_sketch/paths.py`로 파일 위치 규칙을 한곳에 모았습니다.
  - **저장소에서 실행:** `robot/drawing_config.json`, `LOG/runs/`, `out/cache/`, `input/`
  - **설치나 .exe로 실행:** `%APPDATA%\MirobotSketch\` (기본 설정은 패키지의 `data/drawing_config.json`을 복사)
  - `MIROBOT_CONFIG` 환경 변수로 설정 파일을 직접 지정할 수 있음
- `pyproject.toml`:
  - 의존성 8개
  - 선택 설치 `[rembg]`, `[build]`
  - 실행 명령 `mirobot-sketch`(GUI, 콘솔 창 없음), `mirobot-strokes`, `mirobot-draw`, `mirobot-sim`
- `requirements.txt`는 `-e .` 한 줄로 바꿨습니다.

**검증.**
- 깨끗한 가상환경(uv)에 설치했을 때 실행 명령 4개가 만들어졌습니다.
- 설치 모드에서 획 추출, 드로잉 dry-run, 시뮬레이션(PASS)이 모두 동작했습니다.
- 사용자 폴더에 기본 설정이 복사됐습니다.
- `tests/test_paths.py` 5개를 추가해 전체 48개가 통과합니다.
  - 저장소 모드와 설치 모드의 파일 위치
  - 환경 변수 우선순위
  - **패키지 기본 설정과 저장소 설정의 항목 구조 일치**
  - 아이콘 포함 여부
- pyflakes 경고 0개

**작업 중 발견한 버그.**
- **아이콘 경로 일괄 치환 오류:** 치환이 `str(...)` 안쪽에 먼저 적용돼 `strpaths.asset(...)`이라는 잘못된 코드가 생겼습니다. 설치본 GUI 확인에서 발견해 고쳤습니다.
- **rembg 미설치 시 안내:** 원시 ImportError 대신 "`pip install "mirobot-sketch[rembg]"`로 설치하거나 끄세요"라는 안내가 나오게 했습니다. CLI는 오류 추적 없이 메시지와 종료 코드 2를 돌려줍니다.

## 2. Windows .exe (PyInstaller)

- `packaging/mirobot_sketch.spec`: 폴더형(onedir) 빌드입니다. `dist/MirobotSketch/`에 두 실행 파일이 들어갑니다.
  - `MirobotSketch.exe`: GUI, 콘솔 창 없음, 앱 아이콘
  - `mirobot.exe`: 명령줄 도구, 하위 명령 `draw` / `strokes` / `sim`
- 한 파일(onefile)보다 폴더형을 택했습니다. 실행이 빠르고 백신 오탐이 적습니다.
- rembg와 onnxruntime은 제외했습니다. 전역 환경에 있는 다른 패키지가 섞이지 않도록 깨끗한 빌드 전용 가상환경에서 빌드했습니다.

**문제와 해결.**
- `.spec` 파일에서 `Path`를 import하지 않아 빌드가 실패했습니다 → import를 추가했습니다.
- `mirobot.exe`의 하위 명령이 모듈을 문자열 이름(`importlib`)으로 불러와, PyInstaller가 모듈을 포함하지 못했습니다(`ModuleNotFoundError`) → `collect_submodules("mirobot_sketch")`로 숨은 import를 지정했습니다.

**검증** (임시 `APPDATA`로 실행해 실제 사용자 폴더는 건드리지 않음).
- 크기: 296MB(폴더), 빌드 약 5분
- `mirobot.exe strokes`(만화, manga 프리셋): 5.3초. 파이썬 실행과 같은 결과(21.5분 추정, 명령 3629개)
- `mirobot.exe draw` dry-run 정상, `mirobot.exe sim` PASS(2.0초)
- 사용자 폴더에 설정 파일이 만들어짐
- `MirobotSketch.exe`: "Mirobot Sketch" 창이 뜸(첫 실행 12.4초, 백신 검사 영향 가능성)
- GUI .exe 안에서 처리·시뮬레이션 버튼을 눌러 보는 확인은 하지 않았습니다. 같은 코드를 CLI .exe로 확인했습니다.

## 3. 콘솔 인코딩

**정의.** 한국어 Windows 콘솔은 cp949라 한글 출력에 문제가 없습니다. 그러나 영문 Windows나 GitHub의 Windows 러너(cp1252)에서는 한글을 `print`하는 순간 `UnicodeEncodeError`로 멈출 수 있습니다.

**해결.**
- `paths.safe_console()`: 출력할 수 없는 글자는 `?`로 바꿔 출력합니다. 명령줄 도구 3개의 `main()` 시작에서 호출합니다.
- 워크플로에는 `PYTHONIOENCODING=utf-8`을 지정해, 로그에서 한글이 제대로 보이게 했습니다.

**검증.** `PYTHONIOENCODING=cp1252`로 실행해도 멈추지 않고 종료 코드 0으로 끝났습니다.

## 4. GitHub Actions

- `.github/workflows/ci.yml`: main push와 PR 때 실행합니다.
  - Windows / Ubuntu × Python 3.11 / 3.13
  - 설치 → 테스트 48개 → `mirobot-draw`, `mirobot-sim` 동작 확인
  - Ubuntu에는 OpenCV용 `libgl1`을 설치합니다.
- `.github/workflows/release.yml`: `v*` 태그를 push하면 실행합니다.
  - Windows에서 설치 → 테스트 → PyInstaller 빌드 → **빌드된 exe로 draw/sim 동작 확인** → zip
  - zip을 Actions 아티팩트와 GitHub Release에 올립니다(릴리스 노트 자동 생성).
  - 수동 실행하면 아티팩트만 남깁니다.
- 액션 버전: checkout v7, setup-python v7, upload-artifact v7, action-gh-release v3 (2026-09-25 기준 최신 릴리스)
- 첫 실행 결과는 아래 "5. 실제 CI/CD 실행 결과"에 있습니다.

## 5. 실제 CI/CD 실행 결과 (사용자 요청: 커밋·push, MIT 라이선스, 릴리스, CI/CD 구성)

- **MIT 라이선스:** `LICENSE`를 추가했습니다(Copyright 2026 Yoobin Kim). `pyproject.toml`에 `license = "MIT"`와 `license-files`를 지정했고, 이를 위해 setuptools ≥ 77이 필요합니다. 빌드한 wheel 메타데이터에서 `License-Expression: MIT`를 확인했습니다.
- **커밋:** `02c5a2f`를 push했습니다.
- **CI 첫 실행 (run 36097865229):** 4개 조합 모두 성공했습니다(각 약 1분). 조합마다 테스트 48개 OK, `mirobot-draw` dry-run 정상, `mirobot-sim` PASS.
  - GitHub 안내: `ubuntu-latest`가 2026-10-19부터 Ubuntu 26으로 바뀝니다. 지금은 영향이 없고, Dependabot과 CI 결과로 지켜봅니다.
- **CD (run 36098010961, 태그 `v0.1.0`):** 2분 52초 만에 성공했습니다. 설치 → 테스트 → PyInstaller 빌드 → 빌드된 exe로 draw/sim 확인 → zip → 아티팩트와 Release 업로드.
- **릴리스:** https://github.com/yoobinkim541/OSS-2026/releases/tag/v0.1.0
  - `MirobotSketch-v0.1.0-windows-x64.zip`, 130MB
  - 받아서 이 PC에서 실행해 봤습니다: `mirobot.exe sim` PASS, `mirobot.exe strokes` 정상(485획), `MirobotSketch.exe` 창 뜸(첫 실행 15초).
- **추가 구성:**
  - README에 CI, 릴리스, 라이선스 배지를 달았습니다.
  - `.github/dependabot.yml`: Actions와 pip 의존성을 매주 확인합니다.

## 6. main 브랜치 보호 규칙 (사용자 요청)

GitHub API로 적용했습니다(`PUT /repos/yoobinkim541/OSS-2026/branches/main/protection`).

| 규칙 | 설정 | 이유 |
|---|---|---|
| 필수 상태 검사 | CI 4개 조합(`test (windows-latest, 3.11)` 등), GitHub Actions 앱으로 한정 | 테스트를 통과한 변경만 병합 |
| 최신 main 기준 | 켬 (strict) | 오래된 브랜치로 통과한 결과를 인정하지 않음 |
| 강제 push / 브랜치 삭제 | 금지 | 기록 보호 |
| 대화 해결 필수 | 켬 | PR 코멘트가 남아 있으면 병합 불가 |
| 리뷰 승인 | 요구 안 함 | 혼자 하는 프로젝트라 자기 PR을 승인할 수 없음 |
| 관리자 예외 | 켬 (`enforce_admins: false`) | 저장소 주인은 지금처럼 main에 직접 push 가능. Dependabot이나 다른 사람의 PR은 CI를 통과해야 병합됨 |

## 7. 바로가기와 설치 프로그램 (사용자 제안: "바로가기로 클릭해서 실행되면 완성도 있지 않을까")

**개발 PC 바로가기** (`packaging/create_shortcuts.ps1`)
- 바탕화면과 시작 메뉴에 "Mirobot Sketch.lnk"를 만듭니다. 대상은 `pythonw.exe CV\gui_sketch.py`(콘솔 창 없음), 아이콘은 `assets/app_icon.ico`입니다.
- 저장소 코드를 실행하므로, 코드를 고치면 바로 반영됩니다. `-Remove`로 지울 수 있습니다.
- **문제:** BOM 없는 UTF-8 스크립트를 Windows PowerShell 5가 한국어 코드페이지로 읽어, 출력과 바로가기 설명의 한글이 깨졌습니다 → UTF-8 BOM으로 저장해 해결했습니다.
- **검증:** 이 PC에 바로가기를 만들고, 바로가기로 실행해 "Mirobot Sketch" 창이 뜨는 것을 확인했습니다(12.8초). 설명 문구도 정상입니다.

**작업표시줄 묶음**
- pythonw로 실행하면 작업표시줄에서 파이썬 아이콘으로 묶였습니다. 그래서 GUI 시작 시 `SetCurrentProcessExplicitAppUserModelID("YoobinKim.MirobotSketch")`로 앱 고유 ID를 지정했습니다.
- 설치 프로그램의 바로가기에도 같은 ID를 넣었습니다.

**설치 프로그램** (`packaging/installer.iss`, Inno Setup 6)
- 관리자 권한 없이 사용자 폴더에 설치합니다(`PrivilegesRequired=lowest`).
- 바로가기: 시작 메뉴에 앱·명령 프롬프트·제거, 바탕화면은 선택
- MIT 라이선스 동의 화면, 한국어/영어 설치 화면, 설치 후 실행 옵션
- AppId를 고정해, 새 버전을 설치하면 기존 설치를 업그레이드합니다.
- 이 PC에는 Inno Setup이 없어서 GitHub Windows 러너에서 빌드합니다. 러너에 없으면 choco로 설치합니다.

**Release 워크플로 확장**
- 태그와 `__version__`이 일치하는지 검사합니다.
- PyInstaller → 설치 프로그램 빌드 → **러너에서 조용히 설치**(시작 메뉴 바로가기 확인, 설치된 `mirobot.exe sim` 실행) → **조용히 제거**(파일이 사라졌는지 확인)
- zip과 Setup.exe를 함께 올립니다.

버전은 0.1.1로 올렸습니다.

**검증과 공개**
- 수동 실행(run 36102271309): 전 단계가 성공했습니다.
  - Inno Setup 컴파일 61초
  - 러너에서 시작 메뉴 `Mirobot Sketch\Mirobot Sketch.lnk` 생성 확인
  - 설치된 `mirobot.exe sim` 실행 성공
  - 제거 후 파일 삭제 확인
- `v0.1.1` 태그 릴리스(run 36103549610): 성공
  - https://github.com/yoobinkim541/OSS-2026/releases/tag/v0.1.1
  - `MirobotSketch-Setup-0.1.1.exe` 89MB, `MirobotSketch-v0.1.1-windows-x64.zip` 130MB
- 이 PC에 설치 프로그램을 실제로 설치해 보지는 않았습니다(러너에서만 검증). 이 PC는 저장소 코드용 바로가기를 씁니다.

## 남은 일

- (선택) ROS 2 Humble 시뮬레이션용 Dockerfile
- 코드 서명이 없어 SmartScreen이 "알 수 없는 게시자" 경고를 띄울 수 있습니다.
