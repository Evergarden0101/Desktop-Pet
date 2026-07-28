# Character packs

A **character** is a folder containing a `character.json` manifest and,
optionally, a `texture.png` source image and a `parts/` cache of extracted
sprites. Packs live in either location (both are scanned):

- **Bundled:** `assets/characters/<name>/` (ships with the app)
- **User:** `%APPDATA%\DesktopPet\characters\<name>\` (yours)

Select a character from the tray/right-click menu, or with
`desktop-pet run --character <name>`.

## Quick start

**In the app:** right-click the pet (or tray icon) → **Character → Add from a
picture…** (also under **Settings → Manage characters**). Pick an image, name
it, press **Add character**. That same window previews, switches, renames,
duplicates and deletes characters.

**From the command line:**

```bash
# Cut any image into a ready-to-use pack in your user characters dir
desktop-pet extract hero.png --name Hero
desktop-pet run --character Hero
```

Either way this writes `Hero/character.json`, copies the image to
`Hero/texture.png`, and caches the cut sprites in `Hero/parts/`.

## `character.json` reference

Every field is optional except `name`. Unknown fields are ignored, so packs are
forward-compatible.

```jsonc
{
  "name": "Hero",
  "author": "you",
  "version": "1.0",
  "scale": 1.0,                 // default display scale

  // ── How the pet is drawn ─────────────────────────────────────────────
  "render": {
    "mode": "image",            // "image" | "shapes" | "auto"
    // For "shapes" mode (no art needed):
    "outline": "#2b2b3a",
    "outline_width": 3.0,
    "palette": {                // per-part fill colours
      "head": "#ffd9a0", "torso": "#4f8cff", "thigh_l": "#2f3550" /* … */
    },
    "face": { "eye_color": "#2b2b3a", "cheek_color": "#ff9e9e" }
  },

  // ── How body parts are obtained from the source image ────────────────
  "source_image": "texture.png",
  "extraction": {
    "method": "regions",        // "auto_humanoid" | "regions" | "pose"
    "regions": {                // only for "regions": rect = [x0,y0,x1,y1]
      "head":  { "rect": [70, 10, 130, 70],  "pivot": [0.5, 0.9] },
      "torso": { "rect": [65, 70, 135, 210], "pivot": [0.5, 0.05] }
      // … one entry per part
    }
  },

  // ── Skeleton override (empty/absent → the default humanoid rig) ──────
  "skeleton": [
    { "name": "hips",  "parent": null,   "length": 4,  "rest_angle": -1.5708,
      "part": "hips",  "z_order": 5 },
    { "name": "torso", "parent": "hips", "length": 44, "rest_angle": 0.0,
      "part": "torso", "z_order": 6 }
    // …
  ],

  // ── Optional behaviour tuning for this character ─────────────────────
  "behaviors": {
    "walk_speed": 110,
    // Give the character its own voice. Any category you list replaces the
    // built-in one; unlisted categories keep the defaults. Categories:
    // greet, idle, walk, climb, sit, sleep, wake, feed, poke, drag,
    // land_hard, chase, summon, hungry, tired, blocked.
    "phrases": {
      "greet": ["yo!", "在下登场!"],
      "climb": ["up up up!", "看我爬!"]
    }
  }
}
```

### Render modes

| `render.mode` | Uses | When |
| --- | --- | --- |
| `shapes` | `palette` + `outline` | No art; the rig is drawn as coloured capsules + a face. This is how the built-in **Pip** works. |
| `image` | extracted part sprites | Your character has a `texture.png`. |
| `auto` | image if a texture exists, else shapes | Sensible default. |

### Extraction methods

| `method` | Needs | Notes |
| --- | --- | --- |
| `auto_humanoid` | Pillow | Heuristic slice of an upright, front-facing figure. Great starting point. |
| `regions` | Pillow | You give exact rectangles per part — pixel-perfect. `desktop-pet extract` writes these for you (converted from the auto slice) so you can hand-tune them. |
| `pose` | `mediapipe`, `numpy` | Detects joints and cuts around them; falls back to `auto_humanoid` if MediaPipe isn't installed. |

## The skeleton

Bones form a tree; each child attaches at its parent's tip. Fields:

| Field | Meaning |
| --- | --- |
| `name` | Unique bone id |
| `parent` | Parent bone name, or `null` for the root (pelvis) |
| `length` | Bone length in rig units (× `scale` at runtime) |
| `rest_angle` | Default **local** angle (radians), relative to the parent |
| `part` | Body-part sprite drawn on this bone |
| `z_order` | Draw order (higher = in front) |
| `pivot` | `[x, y]` (0..1) where the sprite's joint sits |

**Angle convention:** screen space — `0` points right (+X), `+π/2` points down
(+Y). The standard part names the built-in behaviours animate are:

```
hips, torso, head,
upper_arm_l, forearm_l, hand_l,   upper_arm_r, forearm_r, hand_r,
thigh_l, shin_l, foot_l,          thigh_r, shin_r, foot_r
```

If you omit `skeleton`, the default humanoid rig is used — which is why
`desktop-pet extract` alone is enough for most characters.

## Non-humanoid shapes

You can define any creature by writing your own `skeleton` and `palette`/parts.
For example, a snake is a chain of `torso`-like bones with no legs; a blob is a
single `torso` bone in `shapes` mode. Behaviours that reference missing bones
(e.g. IK on arms during climbing) degrade gracefully — the base pose still
plays — so partial rigs are fine.

## Tips

- Transparent PNGs extract best (the bounding box is found from the alpha
  channel). For opaque images, the top-left pixel colour is treated as the
  background and trimmed.
- After an `auto_humanoid` extract, open `parts/` to see the cuts, then tweak
  the `regions` rectangles in `character.json` and delete `parts/` to force a
  re-extract on next launch.
- Set `render.mode` to `shapes` and tweak the `palette` to recolour the built-in
  mascot without any art at all.
