"""Character Manager tests: import, rebuild, rename, delete, population.

Run headless:  QT_QPA_PLATFORM=offscreen python tests/test_manager.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_pet.app import PetApp  # noqa: E402
from desktop_pet.config import Config  # noqa: E402
from desktop_pet.manager import ImportDialog, ManagerWindow, pil_to_qpixmap  # noqa: E402
from desktop_pet.pipeline import extract as ex  # noqa: E402
from desktop_pet.pipeline import frames as fr  # noqa: E402
from desktop_pet.pipeline.demo import PALETTES, draw_figure  # noqa: E402


def make_photo(path: Path) -> None:
    """A flat-background 'photo' with two people and two distractions."""
    from PIL import ImageDraw

    bg = Image.new("RGBA", (900, 600), (214, 222, 210, 255))
    for i, (_name, skin, hair, dress, shoe) in enumerate(PALETTES):
        fig = draw_figure(skin, hair, dress, shoe)
        fig = fig.resize((int(fig.width * 0.9), int(fig.height * 0.9)))
        bg.alpha_composite(fig, (120 + i * 380, 60))
    d = ImageDraw.Draw(bg)
    d.ellipse([40, 520, 90, 570], fill=(120, 90, 60, 255))       # a prop
    d.rectangle([700, 540, 880, 570], fill=(90, 90, 90, 255))    # a watermark
    bg.convert("RGB").save(path)


def main() -> int:
    qapp = QApplication(sys.argv[:1])
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name} {detail}")
            failures.append(name)

    work = Path(tempfile.mkdtemp(prefix="pet-manager-test-"))
    try:
        pets_dir = work / "assets" / "pets"
        photo = work / "photo.png"
        make_photo(photo)

        cfg = Config()
        cfg.play_chance = 0.0
        app = PetApp(cfg, pets_dir, count=1)

        print("first run")
        check("placeholder characters were created for an empty install",
              len(app.assets) == 2, f"(got {len(app.assets)})")
        check("one pet is on the desktop", len(app.pets) == 1)

        print("the manager window")
        win = ManagerWindow(app)
        win.show()
        qapp.processEvents()
        check("lists every character", win.list.count() == len(app.assets))
        check("selects one by default", win.current_assets() is not None)
        win._next_preview_frame()
        check("renders an animated preview", not win.preview.pixmap().isNull())
        win.anim_toggle.setChecked(True)
        win._load_preview()
        check("can switch to the play animation", len(win._preview_frames) > 0)

        print("population control")
        key = win.current_key()
        app.set_population(key, 3)
        check("spawns up to the requested count", app.population(key) == 3,
              f"(got {app.population(key)})")
        app.set_population(key, 0)
        check("despawns down to zero", app.population(key) == 0)
        check("app survives having no pets", app.pets is not None)
        app.set_population(key, 1)

        print("rename")
        app.roster.set_display_name(key, "小樱")
        win.refresh(select=key)
        check("shows the new name",
              win.list.currentItem().text() == "小樱",
              f"(got {win.list.currentItem().text()!r})")
        check("the name survives a reload",
              app.roster.display_name(key) == "小樱")

        print("importing an image")
        before = {a.name for a in app.assets}
        dialog = ImportDialog(pets_dir)
        dialog._source = Image.open(photo).convert("RGBA")
        dialog.use_rembg.setChecked(False)

        # run detection synchronously, the same call the worker thread makes
        opts = dialog._options()
        rgba, boxes = ex.prepare(dialog._source, opts)
        cutouts = [ex.normalize_height(ex.crop_figure(rgba, b), opts.height)
                   for b in boxes]
        dialog._on_detected((rgba, boxes, cutouts))

        check("finds exactly the two people", len(cutouts) == 2,
              f"(got {len(cutouts)})")
        check("offers one tickable entry per figure",
              dialog.figures.count() == 2)
        check("every figure starts ticked",
              all(dialog.figures.item(i).checkState() == Qt.Checked
                  for i in range(dialog.figures.count())))
        check("no cutout warnings on a clean source",
              all(not ex.cutout_warnings(c) for c in cutouts),
              str([ex.cutout_warnings(c) for c in cutouts]))

        # untick the second, import only the first
        dialog.figures.item(1).setCheckState(Qt.Unchecked)
        chosen = dialog._checked()
        check("only ticked figures are imported", len(chosen) == 1)

        folders = []
        for i, cut in enumerate(chosen, start=1):
            folder = pets_dir / ex._unique_name(pets_dir, "figure", i)
            folder.mkdir(parents=True, exist_ok=True)
            cut.save(folder / "base.png")
            folders.append(folder)
        built = fr.build_all(folders)
        check("the imported figure animates", len(built) == 1)
        check("frames landed on disk",
              len(list(folders[0].glob("crawl_*.png"))) == 8)
        check("meta records a head anchor per frame",
              len((folders[0] / "meta.json").read_text()) > 0)

        app.reload_assets()
        after = {a.name for a in app.assets}
        check("the new character joins the cast", after - before == {folders[0].name},
              f"(new: {after - before})")
        win.refresh(select=folders[0].name)
        check("the manager shows her", win.list.count() == len(app.assets))

        print("rebuild")
        target = folders[0]
        stamp = (target / "crawl_000.png").stat().st_mtime
        (target / "crawl_007.png").unlink()          # simulate a stale build
        fr.build_all([target])
        check("rebuild restores every frame",
              (target / "crawl_007.png").exists())
        check("rebuild rewrites the frames",
              (target / "crawl_000.png").stat().st_mtime >= stamp)

        print("live resize")
        app.set_population(folders[0].name, 1)
        pet = next(p for p in app.pets if p.assets.name == folders[0].name)
        feet_before = pet.bottom
        old_w = pet.width()
        app.set_scale(0.7)
        check("pets resize with the scale slider", pet.width() != old_w,
              f"({old_w} -> {pet.width()})")
        check("her feet stay on the ledge after resizing",
              abs(pet.bottom - feet_before) < 2,
              f"({feet_before:.0f} -> {pet.bottom:.0f})")

        print("delete")
        doomed = folders[0].name
        app.despawn_all(doomed)
        shutil.rmtree(pets_dir / doomed, ignore_errors=True)
        app.roster.forget(doomed)
        app.reload_assets()
        check("the character is gone from disk",
              not (pets_dir / doomed).exists())
        check("and gone from the cast",
              doomed not in {a.name for a in app.assets})
        check("no orphaned pets left behind",
              all(p.assets.name != doomed for p in app.pets))

        print("persistence")
        check("roster.json was written", (pets_dir.parent / "roster.json").exists())

        win.close()
        app.quit()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
