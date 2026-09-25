"""저장소에서 바로 실행하는 시뮬레이터 진입점. 코드는 mirobot_sketch/mirobot_sim.py에 있습니다.

    python sim/mirobot_sim.py trajectories/orientation-test-F.json      (설치 후에는 mirobot-sim)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirobot_sketch.mirobot_sim import main  # noqa: E402

sys.exit(main())
