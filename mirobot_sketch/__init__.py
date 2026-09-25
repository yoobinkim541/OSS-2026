"""Mirobot Sketch — 사진을 WLKATA Mirobot 로봇 팔이 펜으로 그릴 수 있는 선으로 바꾸는 도구.

모듈:
  sketch_pipeline  엣지 -> 획 추적 -> 이중선 제거 -> 이어붙이기 -> 단순화 -> 순서
  paper_mapping    픽셀 -> 종이 mm 변환, JSON 입출력, A4 미리보기
  presets          이미지 종류·상세도 프리셋
  draw_executor    획 JSON -> G-code, 시리얼 실행, 시간 추정   (mirobot-draw)
  mirobot_sim      기구학 시뮬레이션, 관절 한계 검사           (mirobot-sim)
  make_strokes     사진 -> 획 JSON 명령줄 도구                 (mirobot-strokes)
  gui              데스크톱 GUI                                (mirobot-sketch)
"""

__version__ = "0.1.1"
