# 작업 로그

이 폴더는 Mirobot 사진-스케치 프로젝트의 진행, 실험 조건, 관찰 결과, 미해결 항목을 날짜별로 기록합니다.

## 기록 원칙

- 실제 실행 결과, 사용자가 관찰한 결과, 원인에 대한 추정을 구분합니다.
- 측정하지 않은 좌표·압력·보정값은 확정값처럼 기록하지 않습니다.
- 로봇 동작을 바꾼 뒤에는 조건과 결과를 함께 남기고, 재사용 도형은 trajectories/shape-library.json에도 반영합니다.
- JSON 변경 전 스냅샷은 snapshots/에 보관합니다.
- 근거 이미지는 assets/<날짜-주제>/에 보관합니다.

## 세션 기록

- [2026-09-24 — 하트 그리기 결과와 종이 면/X축 접촉 보정 이슈](./2026-09-24-session.md)
- [2026-09-24 — CV 파이프라인, 모델 및 오픈소스 조사](./2026-09-24-cv-model-research.md)
- [2026-09-24 — OpenCV 학습 방향 결정 및 1강 실습 시작](./2026-09-24-opencv-study-kickoff.md)
- [2026-09-24 — 프로젝트 정리, 문제 정의와 해결 (획 추적·종이 변환·실행기)](./2026-09-24-cleanup-and-fixes.md)

## 주요 프로젝트 파일

- [OpenCV 학습 계획과 첫 실습](../docs/opencv-study/lesson-01-image-basics.md)
- [도형 및 실행 이력](../trajectories/shape-library.json)
- [프로젝트 설계 문서](../docs/superpowers/specs/2026-09-23-mirobot-photo-sketch-design.md)
- [드로잉 실행기 설정](../robot/drawing_config.json)
- 실물 실행 기록: runs/ (robot/draw_executor.py --execute 가 자동 생성)
