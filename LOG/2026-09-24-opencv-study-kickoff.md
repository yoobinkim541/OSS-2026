# 2026-09-24 — OpenCV 학습 방향 결정 및 1강 실습 시작

## 결정 사항

앞선 CV/모델 조사 결과 중 OpenCV 중심의 기본 파이프라인을 우선 진행하기로 함. 프로그램 구현에 앞서 OpenCV의 이미지 표현과 기본 영상처리를 학습한다.

- 기준선: OpenCV Canny/threshold 기반 선 후보
- 이후 주제: morphology, contour/approxPolyDP, skeletonize 및 stroke graph 추적
- 선택형 비교: PiDiNet 엣지 검출, 복잡한 배경에서의 SAM2 대상 마스크
- Qwen3-VL은 자연어 입력/실행 결과 설명에 한정하고 로봇 좌표 생성을 맡기지 않음
- 기존 ROS2 Humble/Windows 실물 제어 구조는 유지

## 첫 학습 범위

이미지 배열의 높이·너비·채널, OpenCV의 BGR 순서, 회색조 변환, Gaussian blur, 두 Canny 임계값 설정을 비교한다. 실행 코드는 단계별 중간 이미지를 저장해 파라미터와 결과를 연결해서 볼 수 있게 구성함.

## 생성/수정 파일

- docs/opencv-study/lesson-01-image-basics.md: 개념, 실행법, 관찰 질문, 다음 학습 순서
- docs/opencv-study/lesson-01.py: 회색조/블러/Canny 비교 이미지 생성기
- docs/superpowers/specs/2026-09-23-mirobot-photo-sketch-design.md: 구현 방향 결정사항 추가
- LOG/README.md: 학습 자료와 본 로그 색인 추가

이번 단계에서는 새 CV 패키지를 설치하지 않았고, 로봇으로 경로를 실행하지 않음. 실습은 사용자의 WSL2 Python 환경에서 입력 사진을 대상으로 시작한다.

## 검증 결과

- lesson-01.py는 Python 문법 파싱 검사를 통과함.
- Codex 기본 Python 런타임에는 cv2가 설치되어 있지 않음. 이 런타임에는 패키지를 설치하지 않음.
- 현재 세션에서 WSL 배포판 조회가 권한 거부되어, 사용자의 Ubuntu 안에서 cv2 설치 여부와 실습 실행은 아직 확인하지 못함.
- Ubuntu에서 먼저 python3 -c "import cv2; print(cv2.__version__)"로 확인하고, 성공하면 lesson-01.py 실습을 실행한다.
