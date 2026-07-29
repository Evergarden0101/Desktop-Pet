"""Load the sprite folders produced by tools/make_frames.py."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPixmap, QTransform


@dataclass
class Animation:
    name: str
    fps: int
    right: list[QPixmap]
    left: list[QPixmap]
    head_right: list[QPointF]
    head_left: list[QPointF]

    def __len__(self) -> int:
        return len(self.right)

    def frame(self, index: int, facing_right: bool) -> QPixmap:
        frames = self.right if facing_right else self.left
        return frames[index % len(frames)]

    def head(self, index: int, facing_right: bool) -> QPointF:
        heads = self.head_right if facing_right else self.head_left
        return heads[index % len(heads)]


@dataclass
class PetAssets:
    name: str
    size: tuple[int, int]
    anims: dict[str, Animation]

    def icon_pixmap(self) -> QPixmap:
        return self.anims["play"].right[0]


def load_pet(folder: Path, scale: float) -> PetAssets:
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))

    fw, fh = meta["frame_size"]
    target_w = max(1, int(fw * scale))
    target_h = max(1, int(fh * scale))
    ratio = target_w / fw

    anims: dict[str, Animation] = {}
    for name, spec in meta["anims"].items():
        right, left, head_r, head_l = [], [], [], []
        for file_name, head in zip(spec["frames"], spec["head"]):
            pm = QPixmap(str(folder / file_name))
            if pm.isNull():
                continue
            pm = pm.scaled(target_w, target_h, Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
            right.append(pm)
            left.append(pm.transformed(QTransform().scale(-1, 1),
                                       Qt.SmoothTransformation))
            hx, hy = head[0] * ratio, head[1] * ratio
            head_r.append(QPointF(hx, hy))
            head_l.append(QPointF(target_w - hx, hy))
        if right:
            anims[name] = Animation(name, int(spec.get("fps", 10)),
                                    right, left, head_r, head_l)

    if "crawl" not in anims:
        raise ValueError(f"{folder.name}: no crawl animation")
    anims.setdefault("play", anims["crawl"])

    return PetAssets(meta.get("name", folder.name), (target_w, target_h), anims)


def discover(root: Path, scale: float) -> list[PetAssets]:
    """Every pet folder under ``root`` that has been through make_frames.py."""
    if not root.exists():
        return []
    pets = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (folder / "meta.json").exists():
            continue
        try:
            pets.append(load_pet(folder, scale))
        except (OSError, ValueError, KeyError) as exc:
            print(f"skipping {folder.name}: {exc}")
    return pets
