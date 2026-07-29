# Desktop Pet

Extracts the people out of one image and turns them into desktop pets that
crawl around your screen, climb on your windows, and answer when you call.

![preview](docs/preview.png)

*(The preview uses the built-in placeholder figures — replace them with your
own image, see step 1.)*

- Each figure keeps its **own face, hairstyle and clothing** — those pixels are
  never repainted, only sliced and rotated at the joints.
- Arms and hands are **drawn in**, because a standing photo does not show what
  the hands do while crawling. They are painted in skin and clothing colours
  sampled from that same figure.
- Backgrounds, props and any small blobs are dropped during extraction.
- Pets crawl along the **bottom of the screen and the top edge of every open
  window**, climb low window edges, turn back at tall ones, and fall when they
  crawl off a ledge.
- Right-click any pet → **Call Husband** (喊老公) pops a speech bubble beside
  her head. The other pets answer a moment later.
- The whole pipeline is **built into the app**: import an image, tune the
  cutout with a live preview, and manage your cast from the Character Manager.

## Quick start

```bash
pip install -r requirements.txt
python run.py
```

That's it. On first run, with no characters installed, the app builds the
placeholder cast itself so there is always something on screen. Then right-click
a pet → **Character Manager** to import your own image.

## 1. Use your own image

### From inside the app (no command line)

Right-click any pet → **Character Manager** → **Import image…**

![import](docs/import.png)

Pick your image and the app removes the background, finds the people, and shows
you a cutout of each one. Drag **Background tolerance** and the preview
re-cuts live — that is the fastest way to fix a cutout that lost a limb or kept
a slab of backdrop. Untick anyone you don't want, press **Import**, and they
animate and join the cast.

![manager](docs/manager.png)

From the Character Manager you can also rename a character, change how many
copies of her are on the desktop, resize the whole cast, **Rebuild** her frames,
or **Delete** her for good.

### From the command line

```bash
pip install rembg onnxruntime          # strongly recommended for photos
python tools/extract_figures.py path/to/your-image.jpg
python tools/make_frames.py
python run.py
```

`extract_figures.py` removes the background, splits the remaining mask into one
blob per person, drops everything too small or too wide to be a person, and
writes `assets/pets/figure_01/base.png`, `figure_02/…` and so on. It runs the
exact same code as the Character Manager.

Delete the `assets/pets/demo_*` folders once you have your own figures, or the
demos will show up alongside them — or just remove them in the manager.

**Best results come from a full-body image** — head to feet, figures not
overlapping. The rig locates the neck, waist and knees from the silhouette, so
a portrait crop that stops at the waist has no legs to animate.

If two people are touching, the automatic split will merge them into one blob.
Separate them by hand with pixel boxes:

```bash
python tools/extract_figures.py photo.jpg --boxes 10,20,300,900 320,40,610,900
```

Other useful flags:

| Flag | Meaning |
| --- | --- |
| `--no-rembg` | skip the ML matting, use the border flood fill |
| `--tolerance 30` | flood-fill colour tolerance (the manager's slider) |
| `--min-area 0.002` | keep smaller blobs (use if a figure went missing) |
| `--max-figures 3` | keep only the largest N people |
| `--height 480` | cutout resolution before scaling |

### A note on background removal

`rembg` gives far better cutouts on photographs, but it needs `onnxruntime` and
downloads a model, so it is **not** bundled in the exe. Without it both the app
and the CLI fall back to a border flood fill, which works well on flat or
already-transparent backgrounds. The two ways it fails are worth knowing:

- **tolerance too high** — it eats parts of the figure whose colour is close to
  the background (bare legs against a pale wall are the classic case)
- **tolerance too low** — a slab of background survives around the figure

Both are caught and reported: the manager marks the affected figure with `(!)`
and a tooltip, the CLI prints a warning. Move the slider and watch the preview.

## 2. Build the .exe

On **Windows**:

```bash
pip install -r requirements.txt pyinstaller
python build_exe.py            # --onedir starts faster, --onefile is tidier
```

The result is `dist/DesktopPet.exe`. Double-click it — no Python needed on the
machine you run it on.

Without a Windows machine, push this branch and GitHub Actions builds it for
you: **Actions → Build Windows exe → Run workflow**, then download the
`DesktopPet-windows` artifact. PyInstaller cannot cross-compile, so a Linux or
macOS build produces a binary for *that* platform, not a `.exe`.

You never need to rebuild the exe to change characters — import them from the
Character Manager instead. The exe keeps its assets in a writable folder
(`assets/` next to the exe, or `%LOCALAPPDATA%\DesktopPet\assets` if the exe
sits somewhere read-only like Program Files), seeded from the bundled copy on
first run. Anything you import lands there and survives restarts.

## Controls

| Action | Result |
| --- | --- |
| Right-click a pet | menu: Call Husband, Head Pat, Come Here, Character Manager, Pause, One More, Quit |
| **Call Husband** | speech bubble beside her head; the others answer |
| **Character Manager** | import images, rename, resize, add or remove characters |
| Double-click | same as Call Husband |
| Left-drag | pick her up; let go and she falls to the nearest surface |
| Tray icon | same menu, and the reliable way to quit |

Sending every pet away does not close the app — the tray icon keeps it
reachable, so you can bring them back from the manager.

Menus and bubbles follow your system language (Chinese or English). Force it
with `python run.py --lang zh` or `--lang en`.

## Tuning

`assets/config.json` (or `desktop_pet.json` next to the exe) overrides any
field in `Config`:

```json
{ "scale": 0.42, "speed": 62.0, "max_pets": 8, "language": "auto" }
```

| Key | Meaning |
| --- | --- |
| `scale` | sprite size relative to the generated frames |
| `speed` | crawl speed in pixels per second |
| `climb_height` | how tall a window edge she will climb, as a fraction of her height |
| `play_chance` | chance per tick that she stops to play |
| `obey_window_edges` | `false` = ignore windows, crawl on the desktop floor only |

Command line: `--scale`, `--count`, `--lang`, `--no-window-edges`, `--pets DIR`.

## How the crawl is generated

`tools/make_frames.py` never repaints the figure. For each cutout it:

1. Reads the alpha silhouette and finds the **neck** and **waist** as the
   narrowest rows in the upper third and the middle, then derives shoulders
   and knees from those.
2. Samples **skin** colour from the lower-central head (cheeks and chin, dark
   hair pixels excluded) and **clothing** colour from the upper torso.
3. Slices the cutout into head / torso / thigh / shin layers with a feathered
   cut so the seams disappear once the pieces move.
4. Rotates each layer about its joint into a crawling pose, and draws two arms
   ending in hands — one behind the body and dimmed, one in front — swinging a
   half-cycle apart from the legs.
5. Crops every frame of every animation to one shared box, so the ground
   contact line is always the bottom edge of the frame and she never jitters
   when the animation changes.

`meta.json` records the head position for every frame, which is how the speech
bubble knows where to point.

## Windows and other platforms

Window-edge terrain is Win32-only (`EnumWindows`, skipping cloaked, minimised
and tool windows). On Linux and macOS everything still runs — the pets just
have the desktop floor to themselves, which is what makes the app testable
outside Windows.

## Tests

```bash
QT_QPA_PLATFORM=offscreen python tests/test_physics.py
QT_QPA_PLATFORM=offscreen python tests/test_manager.py
```

`test_physics.py` covers ledge and wall detection, climbing, falling, landing
on window tops, staying on screen, and the speech bubble anchoring to the head.

`test_manager.py` runs a full round trip on a synthetic photo: first-run
seeding, import, per-figure selection, frame generation, rebuild, rename, live
resize, population control and delete.

## Layout

```
src/desktop_pet/pipeline/     the image pipeline, no Qt: importable from both
  rig.py                        joint finding, colour sampling, limb drawing
  extract.py                    image -> one transparent cutout per person
  frames.py                     cutout -> crawl + play frames and meta.json
  demo.py                       placeholder figures
src/desktop_pet/manager.py    Character Manager and the import dialog
src/desktop_pet/pet.py        one pet: physics, dragging, right-click menu
src/desktop_pet/obstacles.py  windows -> ledges and walls
src/desktop_pet/bubble.py     the speech bubble
src/desktop_pet/roster.py     names, and who is on the desktop
src/desktop_pet/app.py        spawning, the clock, the tray icon
tools/*.py                    command-line front ends for the pipeline
build_exe.py                  PyInstaller packaging
```

The pipeline lives inside the package rather than in `tools/` precisely so the
exe can run it: the Character Manager and the CLI call the same functions.
