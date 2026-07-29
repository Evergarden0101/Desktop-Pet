# CLAUDE.md

Guidance for Claude (and humans) working in this repository. Read this before
making changes — it explains the architecture, the invariants that keep the
simulation correct, and how to run/test/build.

## What this is

Desktop Pet is a highly interactive, customizable desktop companion for Windows.
A character (human or anything else) is decomposed into **body sections** that
are rigged to a 2D skeleton, so the pet can perform articulated actions —
walking, running, **climbing** window edges, **creeping**/crawling, sitting,
sleeping, being dragged and thrown — and it **interacts with real application
windows** (standing on title bars, climbing window sides, sitting on the
taskbar).

The app is written in Python with a **PySide6** overlay for rendering, **Pillow**
for body-part extraction, and the **Win32 API via ctypes** for desktop
introspection. It ships as a standalone `DesktopPet.exe` (built with
PyInstaller) and an Inno Setup installer.

## Architecture (layered, GUI-free core)

The package is deliberately layered so the entire simulation can run and be
tested **without a display**. Only the `ui` layer imports PySide6.

```
src/desktop_pet/
├── config.py            AppConfig (user settings) + CharacterPack (a character)
├── characters.py        Character library: import/rename/duplicate/delete (no Qt)
├── cli.py / __main__.py Command line: run | list | extract | new
├── app.py               Bootstraps QApplication and PetApp
├── core/                ← pure logic, no Qt / no Win32
│   ├── geometry.py      Vec2, Rect, clamp/lerp/lerp_angle/smoothstep
│   ├── skeleton.py      Bone hierarchy, forward kinematics, two-bone IK
│   ├── physics.py       PhysicsBody (gravity/throw) + VelocityTracker
│   ├── environment.py   DesktopSnapshot -> walkable Surfaces + climbable Walls
│   ├── state_machine.py Behaviour state machine
│   ├── events.py        Tiny pub/sub bus
│   ├── phrases.py       Bilingual (EN/中文) speech-bubble pools by category
│   └── pet.py           Pet entity: skeleton + physics + stats + state machine
├── rig/
│   ├── body_parts.py    BodyPart, the default humanoid BoneSpec rig
│   ├── extractor.py     Cut a character image into parts (regions/auto/pose)
│   ├── detect.py        Optional MediaPipe pose detection (people in photos)
│   ├── silhouette.py    Alpha-mask analysis + landmarks from detected poses
│   ├── poses.py         PoseLibrary: procedural poses (walk, climb, creep, ...)
│   ├── skeleton_utils.py  Derived measurements (foot-plant offset, span)
│   └── loader.py        CharacterPack -> skeleton + extracted parts
├── behaviors/           ← the pet's actions (states); no Qt
│   ├── base.py, locomotion.py   Behaviour + GroundedBehavior helpers
│   ├── idle/walk/creep/climb/sit/fall/drag/interact.py
│   └── autonomy.py      The "brain" that picks the next action
├── platform/
│   ├── base.py          PlatformBackend interface + get_backend()
│   ├── windows.py       Win32/ctypes backend (enumerate windows/monitors)
│   ├── null.py          Synthetic desktop for dev/CI/tests
│   └── autostart.py     Start-on-login via winreg (Windows)
└── ui/                  ← PySide6 ONLY here
    ├── controller.py    PetApp: owns pets, the frame loop, the tray
    ├── pet_window.py    Transparent click-through overlay (per-pixel mask)
    ├── renderer.py      Draw the rig as shapes or as image parts
    ├── character_dialog.py  Character manager + "add from a picture" importer
    ├── menu.py / tray.py / settings_dialog.py / icon.py / imaging.py
```

### The frame loop (ui/controller.py `_tick`)

```
backend.snapshot()  ->  Environment(snapshot)  ->  for each pet:
    autonomy.update(dt)   # maybe pick a new behaviour
    pet.update(dt)        # behaviour drives physics + pose; solve FK
overlay.refresh()         # repaint + rebuild the click-through mask
```

## Invariants — do not break these

1. **`core`, `rig`, `behaviors`, `platform` must not import PySide6.** The test
   suite imports them headlessly. Keep Qt inside `ui/` (and Pillow imports lazy
   where practical). `tests/test_ui_smoke.py` covers the Qt layer on the
   `offscreen` platform.

2. **The `Environment` is rebuilt every frame** (windows move!). Behaviours must
   **not** cache a `Surface`/`Wall` across frames — re-resolve them each frame
   (see `GroundedBehavior.resolve_support` and `ClimbBehavior._current_wall`).
   This is *why* the pet rides dragged windows and falls when a ledge vanishes.

3. **Foot planting.** `Pet.stand_offset` is the rest-pose distance from the
   skeleton root (pelvis) to the feet. A pet on a surface at height `S` has
   `root.y = S - ground_offset`. Poses that lie/sit lower the `ground_offset`
   (idle behaviours restore it in `on_exit`).

4. **Angle convention** (see `rig/body_parts.py`): screen space, `0` = +X
   (right), `+pi/2` = down. `Bone.local_angle` is relative to the parent;
   `Skeleton.facing` (±1) mirrors the rig for direction of travel.

4b. **Sprite axes.** An image part carries `pivot` (sits on the bone's near
   joint) *and* `child_anchor` (its far end). The renderer maps pivot→bone base
   and anchor→bone tip. `head`, `torso` and `hips` hang off bones that point
   *up*, so their sprites run bottom-to-top; limbs run top-to-bottom. Get this
   wrong and the pivot collapses onto the anchor — the measured axis becomes a
   few pixels and the part is scaled up enormously. `rig/extractor.py::
   _PART_AXES` is the single source of truth; a test asserts no axis degenerates.

5. **Landing is swept** (`behaviors/fall.py`): test the whole
   `[prev_feet, new_feet]` span so a fast fall can't tunnel through a ledge.

6. **Everything is physical pixels.** Win32 reports monitors/windows/cursor in
   physical pixels, so `app.py::_configure_high_dpi` disables Qt's high-DPI
   scaling *before* the QApplication exists — Qt geometry, painting and mouse
   events then share the same unit. Do **not** re-enable Qt scaling or mix
   logical coordinates in: on a 125%/150%-scaled display the pet gets drawn
   below the visible screen and "disappears". (Debug escape hatch:
   `DESKTOP_PET_QT_SCALING=1`.)

7. **`bounding_rect` is the paint region, not the hit-box.** The overlay's
   per-frame mask both routes clicks *and* clips painting, so anything drawn
   outside `Pet.bounding_rect()` is simply invisible — this is why the speech
   bubble is reserved there via `speech_rect()`. Mouse hit-testing uses
   `body_rect()`/`contains_point` instead, so the bubble never becomes a
   grab handle. Add new decorations to `bounding_rect` or they won't show.

8. **Climbing must not filter on `Wall.facing`.** `facing` records which side
   of a wall is climbable, and the pet meets screen edges from the *inside*
   but application-window edges from the *outside*. Filtering on it silently
   restricts climbing to screen edges. Which side to attach is decided from
   the pet's own position (`ClimbBehavior._side`). Reach is judged against
   `Pet.body_height()`, not `stand_offset` — legless "cutout" rigs have a
   stand offset of zero.

9. **Changing `ground_offset` requires re-planting.** It defines where the
   pet's footing is measured from, so a behaviour that changes it (sit, creep,
   sleep) must call `set_feet_on` in the same breath, or the body is left
   hovering, `stick_to_support` finds nothing and the pet falls instead.

10. **Resizing anchors the feet.** `Pet.rescale` recomputes `stand_offset` and
   then moves the root so `feet_y()` is unchanged (preserving any crouch ratio).
   Scaling without this pushes the feet *through* the floor — a large pet ends
   up below the screen.

## Running, testing, building

```bash
# Run from a source checkout (needs PySide6 + Pillow)
python run.py                    # or: python -m desktop_pet
python run.py --backend null     # force the synthetic desktop (no Win32)

# Prepare a character from any image (headless, no PySide6 needed)
python run.py extract art.png --name Hero
python run.py list

# Tests (headless; set offscreen so the Qt smoke tests run)
QT_QPA_PLATFORM=offscreen pytest -q

# Build the Windows executable + installer (on Windows)
build.bat            # -> dist/DesktopPet.exe
build.bat installer  # -> dist/DesktopPet-Setup.exe  (needs Inno Setup)
```

CI (`.github/workflows/build.yml`) runs the tests on Linux and builds/uploads
`DesktopPet.exe` (+ installer) on a Windows runner; tags `v*` attach them to a
GitHub Release.

## Extending

- **New behaviour:** subclass `Behavior` (or `GroundedBehavior`), give it a
  `name`, implement `update(dt) -> Optional[next_state]`, register it in
  `behaviors/__init__.py::DEFAULT_BEHAVIORS`, and (if autonomous) it becomes
  selectable via `AppConfig.enabled_behaviors`.
- **New pose:** add a method to `rig/poses.py::PoseLibrary` returning
  `{bone_name: local_angle}` as small deltas from rest.
- **New phrase:** add to a category in `core/phrases.py` (keep both an English
  and a Chinese line in every category — a test enforces this), then say it with
  `pet.say_category("<category>")`. Packs override via `behaviors.phrases`.
- **New mode:** add an entry to `behaviors/autonomy.py::MODE_WEIGHTS` (weight
  multipliers per behaviour) plus a label in `MODE_LABELS`; menus and the
  settings dialog pick it up automatically.
- **Import analysis order** (`rig/extractor.py::_analyze_best`): pose detection
  (`rig/detect.py`, optional) -> silhouette outline -> proportion bands. The
  detector is always optional and every failure path returns `None`, so import
  never breaks when MediaPipe or its model is absent. Photos *need* it: an
  outline cannot find shoulders under long hair, and the head crop then cuts
  through the face.
- **New character:** drop a folder in the user characters dir with a
  `character.json` (+ optional `texture.png`). See `docs/characters.md`.
- **New platform backend:** implement `PlatformBackend.snapshot()` and wire it
  into `platform/base.py::get_backend`.

## Gotchas

- The overlay uses a **per-frame input mask** built from each pet's
  `bounding_rect()`, so clicks pass through everywhere except over a pet. If
  clicks feel dead, check the mask/bounds math in `ui/pet_window.py`.
- The default character (`Pip`) is **shapes** mode — it needs no art, which is
  why the app works instantly. Image characters fall back to shapes if their
  texture/parts are missing (see `rig/loader.py`).
- Auto body-part extraction (`auto_humanoid`) is a **heuristic**; explicit
  `regions` or the optional `pose` backend (MediaPipe) give cleaner cuts.
```
