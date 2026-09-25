"""저장소에서 바로 실행하는 드로잉 실행기 진입점. 코드는 mirobot_sketch/draw_executor.py에 있습니다.

    python robot/draw_executor.py trajectories/orientation-test-F.json      (설치 후에는 mirobot-draw)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirobot_sketch.draw_executor import main  # noqa: E402

sys.exit(main())
