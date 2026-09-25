"""저장소에서 바로 실행하는 CLI 진입점. 코드는 mirobot_sketch/make_strokes.py에 있습니다.

    python CV/make_strokes.py photo.jpg --type photo      (설치 후에는 mirobot-strokes)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mirobot_sketch.make_strokes import main  # noqa: E402

sys.exit(main())
