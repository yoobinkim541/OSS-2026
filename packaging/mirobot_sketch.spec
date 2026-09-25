# PyInstaller 빌드 설정 — Windows 폴더형(onedir) 배포
#
#   pip install -e ".[build]"
#   pyinstaller packaging/mirobot_sketch.spec --noconfirm
#
# 결과: dist/MirobotSketch/ 안에 MirobotSketch.exe(GUI)와 mirobot.exe(명령줄)
# 한 파일(onefile)보다 폴더형이 실행이 빠르고 백신 오탐이 적습니다.
# rembg(배경 제거)는 용량(모델 약 170MB + onnxruntime) 때문에 넣지 않습니다.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821  (spec 파일 안에서 제공되는 이름)

datas = collect_data_files("customtkinter") + collect_data_files("mirobot_sketch")
excludes = ["rembg", "onnxruntime", "torch", "PyQt5", "PyQt6", "PySide6", "IPython", "jupyter", "pytest"]


def analysis(script):
    return Analysis(  # noqa: F821
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        datas=datas,
        # launch_cli.py는 하위 명령 모듈을 문자열 이름으로 불러오므로 직접 알려 줘야 함
        hiddenimports=["PIL._tkinter_finder"] + collect_submodules("mirobot_sketch"),
        excludes=excludes,
    )


gui = analysis("launch_gui.py")
cli = analysis("launch_cli.py")
icon = str(ROOT / "mirobot_sketch" / "data" / "app_icon.ico")

gui_exe = EXE(  # noqa: F821
    PYZ(gui.pure),  # noqa: F821
    gui.scripts,
    exclude_binaries=True,
    name="MirobotSketch",
    console=False,
    icon=icon,
)
cli_exe = EXE(  # noqa: F821
    PYZ(cli.pure),  # noqa: F821
    cli.scripts,
    exclude_binaries=True,
    name="mirobot",
    console=True,
    icon=icon,
)
COLLECT(  # noqa: F821
    gui_exe, gui.binaries, gui.datas,
    cli_exe, cli.binaries, cli.datas,
    name="MirobotSketch",
)
