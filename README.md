# Open Sourse Software - (2026-2)

- [O] Make a repositories
- [O] write README.md

---

## 텀프로젝트: Mirobot Photo Sketch

사진을 입력하면 OpenCV로 선 경로를 만들고, WLKATA Mirobot 로봇팔이 벽에 붙인 A4 용지에 펜으로 그리는 오픈소스프로그래밍 텀프로젝트입니다.

```
사진 ─▶ CV/make_strokes.py (또는 gui_sketch.py) ─▶ 획 JSON (종이 mm)
     ─▶ robot/draw_executor.py (dry-run → --execute) ─▶ Mirobot 펜 드로잉
```

### 설치

```bash
pip install -r requirements.txt
```

rembg(배경 제거)는 선택 기능입니다. 필요하면 `pip install "rembg[cpu]"`로 따로 설치합니다.

### 사용법

#### 1. 사진 → 획 JSON

```bash
python CV/make_strokes.py photo.jpg --detail medium --out out/photo
```

- `--detail low|medium|high` : 상세도 프리셋. 낮출수록 획 수와 그리는 시간이 줄어듭니다.
- `--lines dark` : 선화나 일러스트처럼 어두운 선이 곧 그릴 선인 입력에 씁니다. 선의 중심선을 한 줄로 그립니다.
- `--rembg` : 배경을 제거한 뒤 처리합니다.
- `--median 7` : 만화 스크린톤(망점)처럼 작은 무늬를 지웁니다.
- `--box W H` : 그리기 상자 크기(mm). 기본값은 100 × 100입니다.

`out/photo.json`과 비교 이미지 `out/photo_preview.png`(입력 / 선 후보 / 획 / 그리는 순서)가 만들어집니다. 같은 작업을 GUI로 하려면 `python CV/gui_sketch.py`를 실행합니다.

#### 2. 획 JSON → 로봇

```bash
python robot/draw_executor.py out/photo.json
```

기본은 **dry-run**이라 로봇을 움직이지 않고 G-code 파일과 요약만 만듭니다. 실제로 그리기 전에 다음을 준비합니다.

1. 전원을 켜고 중앙 버튼을 2초 눌러 호밍한 뒤 Idle 상태를 확인합니다.
2. 펜 끝을 종이 중앙에 둡니다.
3. `robot/drawing_config.json`의 포트, 중심 TCP, 부호를 확인합니다.

준비가 끝나면 실행합니다.

```bash
python robot/draw_executor.py out/photo.json --execute
```

실행 결과는 `LOG/runs/`에 저장됩니다. 처음 실행할 때는 `trajectories/orientation-test-F.json`으로 좌우·상하 방향부터 확인하세요.

- `--air` : 펜을 종이에 대지 않고 같은 경로를 따라갑니다(도달 범위·충돌 확인용).
- `--pending-limits` : 실물 확인 전의 확장 범위(±60mm)로 검사합니다. 범위 확인 시험(`trajectories/border-test-60mm.json`)에만 씁니다.

그리기 범위를 ±50mm에서 ±60mm로 넓히는 절차는 `robot/drawing_config.json`의 `_limits_pending_note`를 따릅니다.

### 3D 시뮬레이션 (로봇 없이 확인)

실행기와 같은 경로로 Mirobot 기구학(IK)을 풀어 관절 한계(Soft limit)를 넘는지 검사합니다.

```bash
python sim/mirobot_sim.py out/photo.json --plot out/joints.png --gif out/sim.gif
python sim/mirobot_sim.py --reach-map out/reach_map.png
```

RViz에서 실제 Mirobot 3D 모델로 재생하려면 궤적을 내보낸 뒤 WSL2(ROS 2 Humble)에서 실행합니다.

```bash
python sim/mirobot_sim.py out/photo.json --export out/photo_traj.json
wsl -d Ubuntu-22.04 -- bash -lc "cd /mnt/c/Users/asus/Desktop/Mirobot && bash sim/run_rviz.sh out/photo_traj.json 10"
```

### 테스트

```bash
python -m unittest discover -s tests -v
```

### 폴더

| 경로 | 내용 |
|---|---|
| `CV/` | 이미지 → 획 파이프라인, GUI, 명령줄 도구 (`experiments/`는 학습 단계 스크립트) |
| `robot/` | 드로잉 실행기와 설정, 초기 시리얼·그리퍼·펌프 시험 코드 |
| `sim/` | 기구학 시뮬레이터, 도달 지도, RViz 재생 |
| `trajectories/` | 도형 템플릿과 테스트 경로 |
| `docs/` | 설계 문서, OpenCV 학습 자료 |
| `LOG/` | 날짜별 작업 기록, 실행 기록 |
| `tests/` | 회귀 테스트 |

### 환경 메모

- 실물 제어는 Windows pyserial로 합니다. WSL2에 USB 패스스루한 CH340 포트는 응답을 읽지 못합니다.
- 시리얼 포트를 새로 열면 보드가 리셋됩니다. 실행 중에는 다른 프로그램이 같은 포트를 열지 않게 합니다.
- ROS 2 Humble / MoveIt 2(WSL2)는 경로 검토와 시각화에 사용합니다.
