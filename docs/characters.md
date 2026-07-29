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
| `image` | extracted part sprites | Your character has a `texture.png` and every part could be cut from it. |
| `hybrid` | sprites *and* `palette` | Some parts came from the picture, the rest are painted. See below. |
| `auto` | image if a texture exists, else shapes | Sensible default. |

#### `hybrid`: a picture with drawn limbs

Most pictures of people can't supply every body part. Arms folded across the
chest leave no gap to cut along; a shot cropped at the thigh has no legs in it
at all. Slicing "legs" out of a block of denim gives a pet that walks on two
rectangles, and leaving the arms baked into the torso gives a pet with no arm
bones — so it can't reach for a ledge while climbing or wave when poked.

In `hybrid` mode each bone draws its sprite **if it has one**, and is otherwise
painted as a tapered capsule in a colour sampled from the picture itself. The
importer chooses this automatically; the extra fields it writes are:

```jsonc
"render": {
  "mode": "hybrid",
  "palette":       { "upper_arm_l": "#d15e38", "thigh_l": "#783826", … },
  "limb_radii":    { "upper_arm_l": 13.9, "thigh_l": 24.2, … },  // half-widths
  "joint_offsets": { "torso": 22.0, "hips": 9.0 },  // how far off centre
  "outline": "#00000000", "outline_width": 0.0
}
```

`joint_offsets` matters more than it looks: the rig hangs both arms off a single
point at the top of the torso, which reads fine on a narrow capsule but puts a
photograph's arms in the middle of its chest. The offsets move each limb chain
sideways — rigidly, so nothing bends at the shoulder.

Drawn limbs are sized in **head heights** (thigh 1.70, shin 1.55, upper arm
1.15, and so on), because the picture has no length to measure. The "head" used
is the smaller of the head crop and shoulder-to-hip ÷ 2.2 — a close-up portrait
has a huge head crop, and quoting limbs in it puts the pet on stilts.

### Extraction methods

| `method` | Needs | Notes |
| --- | --- | --- |
| `auto_humanoid` | Pillow | Best available: person detection if MediaPipe is installed, else silhouette analysis, else proportion bands. |
| `regions` | Pillow | You give exact rectangles per part — pixel-perfect. `desktop-pet extract` writes these for you (converted from the auto slice) so you can hand-tune them. |
| `pose` | `mediapipe`, `numpy` | Same as `auto_humanoid` but makes the intent explicit. Person detection is used automatically whenever it's available. |

**Photographs need the detector**, for three separate reasons:

1. **The background has to go.** A photo is an opaque rectangle, so every crop
   taken from it carries a slab of wall or sky and the pet ends up with corners.
   The model returns a per-pixel person mask, which becomes the image's alpha
   channel before anything is measured or cut.
2. **The shoulders have to be found.** Reading only the outline, a photo where
   hair falls over the shoulders has its widest upper-body point *inside the
   hair*, so the head is measured far too short and the crop cuts through the
   face.
3. **Missing limbs have to be *known* missing.** Landmarks carry a visibility
   score, so "there are no knees or ankles in this photo" is a measurement — and
   that's what selects `hybrid` mode. Without a detector a failed leg split just
   means the legs are pressed together, so those pixels are cut as legs, as
   before.

Check what you'll get with `desktop-pet doctor`.

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
