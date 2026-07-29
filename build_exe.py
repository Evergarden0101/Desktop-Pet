"""Build DesktopPet.exe with PyInstaller.

    pip install -r requirements.txt pyinstaller
    python build_exe.py

The result lands in ``dist/``.  Run this on Windows: PyInstaller does not
cross-compile, so a Linux or macOS run produces a binary for *that* platform,
not a .exe.  If you have no Windows machine, push the branch and let
.github/workflows/build-windows.yml build it for you.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "DesktopPet"


def make_icon(dest: Path) -> Path | None:
    """Build an .ico out of the first pet's frame."""
    try:
        from PIL import Image
    except ImportError:
        return None

    candidates = sorted((ROOT / "assets" / "pets").glob("*/play_000.png"))
    if not candidates:
        candidates = sorted((ROOT / "assets" / "pets").glob("*/crawl_000.png"))
    if not candidates:
        return None

    src = Image.open(candidates[0]).convert("RGBA")
    box = src.getbbox()
    if box:
        src = src.crop(box)

    side = max(src.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(src, ((side - src.width) // 2, (side - src.height) // 2))
    square.resize((256, 256), Image.LANCZOS).save(
        dest, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onedir", action="store_true",
                    help="folder build instead of a single file (starts faster)")
    ap.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    args = ap.parse_args()

    pets = ROOT / "assets" / "pets"
    if not any(pets.glob("*/meta.json")):
        print("error: no built pets in assets/pets.\n"
              "  python tools/make_demo_figures.py     (or extract_figures.py <image>)\n"
              "  python tools/make_frames.py", file=sys.stderr)
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("error: pip install pyinstaller", file=sys.stderr)
        return 1

    if args.clean:
        for folder in ("build", "dist"):
            shutil.rmtree(ROOT / folder, ignore_errors=True)

    if sys.platform != "win32":
        print("warning: not running on Windows -- PyInstaller will produce a binary "
              f"for {sys.platform}, not a .exe\n")

    (ROOT / "build").mkdir(parents=True, exist_ok=True)
    icon = make_icon(ROOT / "build" / "pet.ico")

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--windowed",                      # no console window
        "--name", NAME,
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--onedir" if args.onedir else "--onefile",
        # PySide6 ships far more than we use; dropping these keeps the exe small
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "scipy",
    ]
    if icon and icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(ROOT / "run.py"))

    print(" ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    print(f"\nbuilt: {ROOT / 'dist' / NAME}{'.exe' if os.name == 'nt' else ''}")
    print("tip: drop an 'assets' folder next to the exe to swap in new figures "
          "without rebuilding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
