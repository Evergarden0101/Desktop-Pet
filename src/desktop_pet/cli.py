"""Command-line interface: run the pet, or prepare character packs.

Usage examples::

    desktop-pet                       # run the pet (default)
    desktop-pet run                   # ...same
    desktop-pet list                  # list installed characters
    desktop-pet extract hero.png      # cut hero.png into a character pack
    desktop-pet extract hero.png --name Hero --method auto_humanoid
    desktop-pet new Hero --image hero.png

The ``extract``/``new``/``list`` commands never import PySide6, so they work in
headless environments and in CI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import List, Optional

from . import __version__
from .config import (
    AppConfig,
    CharacterPack,
    discover_characters,
    user_characters_dir,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="desktop-pet",
        description="A highly interactive, customizable desktop pet.",
    )
    parser.add_argument("--version", action="version", version=f"desktop-pet {__version__}")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run the desktop pet (default).")
    run_p.add_argument("--character", help="Character pack name to use.")
    run_p.add_argument("--backend", choices=["auto", "windows", "null"], help="Desktop backend.")

    sub.add_parser("list", help="List installed character packs.")

    extract_p = sub.add_parser("extract", help="Extract body parts from an image into a pack.")
    extract_p.add_argument("image", help="Path to the character image (PNG with transparency ideal).")
    extract_p.add_argument("--name", help="Character name (defaults to the file name).")
    extract_p.add_argument(
        "--method",
        choices=["auto_humanoid", "pose", "regions"],
        default="auto_humanoid",
        help="Extraction strategy.",
    )
    extract_p.add_argument("--scale", type=float, default=1.0, help="Default display scale.")
    extract_p.add_argument("--out", help="Output directory (defaults to the user characters dir).")

    new_p = sub.add_parser("new", help="Create a new character pack from an image.")
    new_p.add_argument("name", help="Character name.")
    new_p.add_argument("--image", required=True, help="Source image path.")
    new_p.add_argument("--method", choices=["auto_humanoid", "pose", "regions"], default="auto_humanoid")

    return parser


def cmd_list() -> int:
    chars = discover_characters()
    if not chars:
        print("No characters installed. The built-in 'default' will be used.")
        return 0
    print("Installed characters:")
    for name, directory in chars.items():
        pack = CharacterPack.load(directory)
        tex = "image" if pack.has_texture else "shapes"
        print(f"  - {name:16s} [{tex}]  {directory}")
    return 0


def cmd_extract(
    image_path: str,
    name: Optional[str],
    method: str,
    scale: float = 1.0,
    out: Optional[str] = None,
) -> int:
    try:
        from PIL import Image
    except Exception:
        print("Pillow is required for extraction:  pip install Pillow", file=sys.stderr)
        return 2

    if not os.path.exists(image_path):
        print(f"Image not found: {image_path}", file=sys.stderr)
        return 2

    from .rig import extractor

    name = name or os.path.splitext(os.path.basename(image_path))[0]
    base = out or user_characters_dir()
    directory = os.path.join(base, name)
    os.makedirs(directory, exist_ok=True)

    image = Image.open(image_path).convert("RGBA")
    result = extractor.extract(image, method=method)

    # Copy the source texture and cache the cut parts.
    texture_name = "texture.png"
    image.save(os.path.join(directory, texture_name))
    parts_dir = os.path.join(directory, "parts")
    extractor.save_parts(result, parts_dir)

    pack = CharacterPack(
        name=name,
        directory=directory,
        source_image=texture_name,
        scale=scale,
        extraction={"method": "regions", "regions": result.to_regions_dict()},
        render={"mode": "image"},
    )
    pack.save_manifest()

    print(f"Created character '{name}' at {directory}")
    print(f"  parts extracted: {len(result.parts)} (method: {result.method})")
    print(f"  run it with:  desktop-pet run --character {name}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command or "run"

    if command == "list":
        return cmd_list()

    if command == "extract":
        return cmd_extract(args.image, args.name, args.method, args.scale, args.out)

    if command == "new":
        return cmd_extract(args.image, args.name, args.method)

    # Default: run the GUI.
    from .app import run

    config = AppConfig.load()
    if getattr(args, "character", None):
        config.character = args.character
    if getattr(args, "backend", None):
        config.backend = args.backend
    return run(config)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
