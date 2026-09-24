# CV 프로그램 및 모델/오픈소스 조사

조사일: 2026-09-24  
프로젝트: WLKATA Mirobot 사진 → 스케치 경로 → 펜 드로잉

## 결론

첫 버전은 **OpenCV + scikit-image 기반의 설명 가능한 파이프라인**으로 구현하고, PiDiNet을 Canny와 비교하는 선택형 엣지 검출기로 평가하는 것을 권장한다. 이미지에서 로봇용 선 경로를 한 번에 만들어 주는 단일 모델을 고르기보다, 대상 선택·선 추출·중심선화·경로 단순화·종이 좌표 변환을 별도 단계로 둔다.

Qwen은 사진을 벡터 경로로 직접 바꾸거나 로봇 좌표를 결정하는 역할보다, 사용자가 원하는 대상/스타일을 묻고 실행 후 사진의 이상을 설명하는 보조 역할이 적합하다. 실제 경로 점과 로봇 동작은 재현 가능한 CV 코드와 안전 검사기가 결정하도록 한다.

## 제안 파이프라인

1. **입력과 선택** — 이미지를 불러와 회전/자르기/대상 영역을 미리 보여준다. 복잡한 사진이면 사용자가 클릭/박스로 대상을 고르게 하고 선택 마스크를 저장한다.
2. **전처리** — 그레이스케일, 크기 정규화, 필요 시 노이즈 제거와 대비 조절을 수행한다. 원본과 각 중간 결과를 함께 저장한다.
3. **선 후보 생성** — 기본 모드는 OpenCV Canny 또는 이진화. 실험 모드는 PiDiNet 확률 엣지맵, 일러스트 입력 실험은 Anime2Sketch 결과를 사용한다.
4. **선 정리** — 임계값, 작은 연결 성분 제거, 끊어진 부분 연결을 조절한다. 복잡한 사진이면 선택 마스크 바깥쪽이나 짧은 텍스처 선을 제거한다.
5. **경로 해석** — 목표가 실루엣이면 닫힌 외곽 contour를 추출한다. 목표가 한 줄 스케치면 이진 선을 얇게 만든 뒤 skeleton 픽셀 그래프를 stroke로 추적한다. 이 두 표현을 하나로 취급하지 않는다.
6. **단순화와 순서** — Douglas–Peucker/approxPolyDP 등으로 점을 줄이고, 너무 짧은 스트로크를 걸러낸다. 펜이 종이 위에 있는 이동을 줄이도록 stroke 순서를 정한다.
7. **종이 배치와 미리보기** — 가로세로 비율을 유지해 안전 여백 안에 넣고 경계 상자 중심을 A4 가로 종이의 중앙에 맞춘다. 선 추출 결과와 실제 로봇 경로를 함께 미리보기한다.
8. **내보내기/실행** — 각 stroke를 Y-Z mm 점 목록으로 변환하고 단위, 종이 중심, 펜업/펜다운, 보정 버전을 JSON에 저장한다. Windows의 기존 실행기가 이를 읽어 전송한다.

OpenCV 문서는 findContours가 이진 영상의 경계 좌표를 돌려주며, approxPolyDP가 곡선의 꼭짓점을 지정 오차 안에서 줄이는 용도임을 설명한다. 따라서 approxPolyDP는 지저분한 의미 없는 선을 알아서 골라내지 않는다. Canny가 폭이 있는 윤곽의 양쪽 경계를 만든 경우 두 contour가 나올 수 있어, 원하는 결과가 한 줄 중심선이라면 별도의 선 정리/중심선화/추적이 필요하다. [OpenCV contour 문서](https://docs.opencv.org/4.12.0/d4/d73/tutorial_py_contours_begin.html), [approxPolyDP 문서](https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html)

실선/두꺼운 선의 중심 경로에는 scikit-image의 skeletonize가 이진 영역을 1픽셀 너비 skeleton으로 줄이는 출발점이 될 수 있다. 이후 분기점, 끝점, 고립 픽셀을 그래프로 추적하고 짧은 가지를 정리하는 작업은 별도로 구현해야 한다. skeletonize 자체가 스트로크 순서나 스케치 의도를 알아내지는 않는다. [scikit-image skeletonize 문서](https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html)

## 참고할 오픈소스 프로젝트

| 프로젝트 | 이 프로젝트에서 참고할 점 | 제약/적합도 |
|---|---|---|
| [OpenCV](https://github.com/opencv/opencv) | Canny, threshold, findContours, approxPolyDP, morphology 등 기본 영상처리. 첫 버전의 기준선과 UI 파라미터 실험에 적합. | 엣지 검출 결과는 선의 의미를 알지 못하므로 사진 질감도 잡을 수 있음. |
| [scikit-image](https://github.com/scikit-image/scikit-image) | skeletonize/thin 및 이진 morphology. 넓은 검은 선을 한 줄 경로로 바꾸는 실험에 사용. | skeleton 픽셀을 연속 stroke로 추적하고 잡가지를 잘라내는 로직은 별도 필요. |
| [PiDiNet](https://github.com/hellozhuo/pidinet) | ICCV 2021 경량 엣지 검출 연구의 PyTorch 코드와 사전학습 결과. Canny 대비 자연 사진에서 선 후보가 얼마나 나아지는지 평가할 후보. | 저장소 라이선스는 연구 목적을 명시하고 상업적 사용은 저자 문의를 요구함. 코드/체크포인트 배포 조건을 프로젝트 공개 전에 확인할 것. 오래된 연구 코드라 현재 PyTorch/CUDA 환경에서 재현 테스트 필요. |
| [Anime2Sketch](https://github.com/Mukosame/Anime2Sketch) | 애니/만화/일러스트에서 선화 형태를 뽑는 사전학습 모델. 입력 유형별 분기 실험에 적합. 저장소는 MIT 라이선스. | 자연 사진의 일반 목적 선 추출 모델로 간주하면 안 됨. 저장소 안내는 입력을 512 크기로 줄이고 Google Drive 체크포인트를 받도록 되어 있어 설치와 재배포 조건을 확인할 것. |
| [SAM 2](https://github.com/facebookresearch/sam2) | 클릭/박스 기반으로 이미지에서 그릴 주 대상을 선택해 마스크를 만들 수 있음. 이후 마스크 안에서 OpenCV 선 추출. 이미지·비디오 지원. | 선 생성기가 아니라 대상 분할 모델. 공식 저장소는 체크포인트/코드를 Apache 2.0으로 배포하며 Python ≥3.10, PyTorch ≥2.5.1을 요구. ROS2 Humble과 의존성을 섞지 않도록 별도 가상환경에서 실험 권장. |
| [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) / [공식 코드](https://github.com/QwenLM/Qwen3-VL) | 사용자가 원하는 대상을 말로 지정하거나, 중간 단계/완성 사진을 보고 누락·겹침·잘못된 대상 같은 문제를 설명하는 보조 모델. 이미지와 비디오 입력 가능. 모델 카드에는 Apache-2.0으로 표시됨. | 자유 생성 응답은 픽셀 단위 재현성이 없으므로 경로 점이나 G-code 생성에 직접 사용하지 않는다. 작은 Instruct 모델부터 RTX 5080에서 메모리/지연을 직접 측정. |
| [vpype](https://vpype.readthedocs.io/en/latest/) | SVG/폴리라인에 linesimplify, linesort 등 플로터용 경로 정리/펜업 이동 최적화를 적용하는 참고 구현. | 이미지 CV 모델은 아니며 Mirobot 전용 실행기도 아님. 자체 Y-Z 좌표 JSON 출력은 별도로 구현해야 함. |
| [WLKATA Python SDK](https://github.com/wlkata/WLKATA-Python-SDK-wlkatapython) / [Mirobot ROS2 저장소](https://github.com/wlkata/Wlkata_Mirobot_Ros2) | 현재 프로젝트의 마지막 단계인 G-code/시리얼 및 ROS2 연결 구조를 비교할 공식 참고 자료. 사용 중인 자체 제어 코드와 함께 확인. | 사용자 환경에서 실측한 Windows 시리얼 제약과 펜 접촉 보정이 우선. 저장소 예제가 현재 USB 연결에서 그대로 동작한다고 가정하지 않음. |

### 최신 모델이지만 첫 선택으로는 보류

[Meta SAM 3 저장소](https://github.com/facebookresearch/sam3)는 텍스트로 대상을 지정하는 분할을 지원하고 SAM 3.1 체크포인트도 공개되어 있다. 다만 저장소가 SAM License를 사용하고 체크포인트 접근 승인이 필요하며, 안내된 환경은 Python ≥3.12, PyTorch ≥2.7, CUDA ≥12.6, 모델은 848M 파라미터다. 기존 ROS2 Humble 환경(Python 3.10 계열)에 바로 추가하기에는 부담이 크므로, SAM 2의 수동 클릭/박스 분할로 먼저 검증한 뒤 필요성이 확인되면 별도 환경에서 비교하는 편이 현실적이다.

## 모델 역할 결정

- **기본 선 생성:** OpenCV Canny + 이진화/morphology + 작은 성분 필터.
- **중심선 스케치 모드:** 깨끗한 이진 선화 → scikit-image skeletonize → skeleton graph 추적 → 짧은 가지 제거 → polyline 단순화.
- **실루엣 모드:** (필요하면 SAM2로 대상 마스크) → 마스크 외곽 contour → approxPolyDP.
- **학습 모델 비교:** PiDiNet을 같은 이미지 세트에 실행하고 Canny와 미리보기/경로 지표를 비교. 점수가 더 좋아지는 경우에만 옵션으로 유지.
- **일러스트 모드:** Anime2Sketch를 별도 실험기로 제공. 사진용 Canny/PiDiNet과 동일한 품질을 기대하지 않음.
- **자연어/관찰 보조:** Qwen3-VL은 대상/스타일 상호작용과 실행 후 설명만 담당. OpenCV 출력과 사용자 승인이 경로 결정의 근거.
- **경로 최적화:** vpype의 simplification/order 아이디어를 참고하고, Mirobot 경로 JSON으로 변환하는 기능은 프로젝트 코드에 둔다.

## 평가 계획

같은 해상도·종이 크기에서 다음 입력 유형을 최소 하나씩 비교한다: 단순 물체 사진, 질감이 많은 물체/배경 사진, 인물 또는 반려동물, 일러스트. 각 입력마다 Canny, PiDiNet(가능하면), 선택 마스크 적용 여부를 저장한다.

기록할 지표는 정답률 하나가 아니라 다음을 함께 사용한다.

- 사용자가 원하는 형태가 알아볼 수 있는지와 불필요한 선 개수
- 끊긴 선/고립 점/짧은 잡선 개수
- 스트로크 수, 총 펜 접촉 길이, 펜업 이동거리
- 단순화 전후 점 수, 예상 로봇 실행 시간
- 사용자가 미리보기에서 선을 지우거나 다시 선택한 횟수
- 실제 종이 출력의 누락/겹침/위치 편차

## 구현 순서 제안

1. OpenCV 전처리, Canny/threshold, contour 및 skeleton 두 모드를 나누어 이미지 미리보기까지 구현.
2. 이미지별 파라미터와 중간 결과를 파일로 저장해 재현 가능하게 함.
3. pixel→mm 변환과 종이 중심 정렬을 붙이고, 펜 접촉/X 평면 보정 완료 후 짧은 경로부터 출력.
4. 샘플 이미지 세트에서 결과와 경로 지표를 기록.
5. Canny가 실패하는 유형만 PiDiNet 또는 SAM2를 비교하고, 발표에서 전통 CV와 모델 기반 선택을 수치와 출력물로 설명.
6. 이후 Qwen3-VL을 사진 설명/실패 관찰에 연결하되 실행 결정은 일반 코드의 상태·범위 검사에 맡김.

이 순서는 모델이 뽑은 보기 좋은 래스터 이미지와 실제 한 획씩 그릴 수 있는 로봇 경로를 혼동하지 않도록 한다. CV 출력은 항상 실행 전 미리보기를 거치고, 종이 범위/이동량/펜 상태를 확인한 뒤 로봇으로 보낸다.

## 참고 링크 모음

- [OpenCV contour tutorial](https://docs.opencv.org/4.12.0/d4/d73/tutorial_py_contours_begin.html)
- [OpenCV approxPolyDP API](https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html)
- [scikit-image skeletonize](https://scikit-image.org/docs/stable/auto_examples/edges/plot_skeleton.html)
- [PiDiNet code and paper results](https://github.com/hellozhuo/pidinet)
- [Anime2Sketch code and license](https://github.com/Mukosame/Anime2Sketch)
- [SAM 2 code, requirements, and license](https://github.com/facebookresearch/sam2)
- [Qwen3-VL official repository](https://github.com/QwenLM/Qwen3-VL)
- [Qwen3-VL-4B model card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)
- [vpype documentation](https://vpype.readthedocs.io/en/latest/)
- [WLKATA Python SDK](https://github.com/wlkata/WLKATA-Python-SDK-wlkatapython)
- [WLKATA Mirobot ROS2](https://github.com/wlkata/Wlkata_Mirobot_Ros2)
