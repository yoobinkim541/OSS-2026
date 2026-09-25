"""저장소에서 바로 실행하는 GUI 진입점. 코드는 mirobot_sketch/gui.py에 있습니다.

    python CV/gui_sketch.py      (설치 후에는 mirobot-sketch)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirobot_sketch.gui import main  # noqa: E402

main()
