"""Image -> animated pet, with no Qt dependency.

Everything here works on PIL images and folders, so it can be driven from the
command line (``tools/``) or from the Character Manager inside the running app.
"""

from .extract import (DEFAULT_TOLERANCE, ExtractOptions, detect_figures,
                      extract_to_folders, remove_background)
from .frames import build_all, build_figure
from .rig import analyze

__all__ = [
    "DEFAULT_TOLERANCE",
    "ExtractOptions",
    "detect_figures",
    "extract_to_folders",
    "remove_background",
    "build_all",
    "build_figure",
    "analyze",
]
