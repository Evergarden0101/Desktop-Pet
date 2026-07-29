"""Turn a static cutout into crawl and play animation frames.

The figure's own pixels are never repainted.  The cutout is sliced into head /
torso / thigh / shin layers along the alpha silhouette and each layer is
rotated about its joint, so face, hairstyle and clothing survive exactly as
they were.  Only the arms and hands -- which a standing photo does not show in
a crawling pose -- are drawn, in the skin and clothing colours sampled from
that same figure.

All frames of one figure share a single crop, so the ground contact line is
always the bottom of the frame.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from .rig import (analyze, slice_parts, part_pivot, paste_rotated, draw_arm,
                  draw_shadow, save_meta)


CRAWL_FRAMES = 8
PLAY_FRAMES = 6
CRAWL_FPS = 10
PLAY_FPS = 8


def rot_vec(d, angle_deg):
    """Rotate an offset the same way PIL's ``rotate`` moves pixels."""
    a = math.radians(angle_deg)
    return (math.cos(a) * d[0] + math.sin(a) * d[1],
            -math.sin(a) * d[0] + math.cos(a) * d[1])


def add(p, q):
    return (p[0] + q[0], p[1] + q[1])


def lerp(a, b, t):
    return a + (b - a) * t


def ease(t):
    """Smooth 0..1 ramp so limbs accelerate and settle instead of sliding."""
    return 0.5 - 0.5 * math.cos(math.pi * t)


# --------------------------------------------------------------------------
# one crawl frame
# --------------------------------------------------------------------------

def crawl_frame(parts, rig, canvas_size, phase: float):
    """Compose a single frame of the crawl cycle, figure facing right."""
    H = rig.bottom - rig.top
    W, Ch = canvas_size
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

    ground = Ch * 0.80
    # near/far limbs are half a cycle apart, which is what makes it read as a crawl
    near = phase
    far = (phase + 0.5) % 1.0

    # torso rocks and the hips bob slightly as weight shifts
    rock = math.sin(phase * 2 * math.pi) * 3.0
    bob = math.cos(phase * 4 * math.pi) * H * 0.012

    torso_angle = -72.0 + rock
    hip = (W * 0.40, ground - H * 0.30 + bob)

    neck = add(hip, rot_vec((rig.head_cx - rig.hip_cx, rig.neck_y - rig.hip_y), torso_angle))
    shoulder = add(hip, rot_vec((rig.shoulder_cx - rig.hip_cx, rig.shoulder_y - rig.hip_y),
                                torso_angle))
    head_angle = -26.0 + rock * 0.6 + math.sin(phase * 2 * math.pi) * 4.0

    upper_len = H * 0.26
    fore_len = H * 0.24
    thickness = max(4.0, H * 0.085)

    def arm_angles(p):
        """Plant -> push back -> lift -> reach forward, as a single loop."""
        if p < 0.5:                       # hand on the ground, pushing backwards
            t = ease(p / 0.5)
            return lerp(52, 88, t), lerp(78, 104, t), 0.0
        t = ease((p - 0.5) / 0.5)         # swing forward through the air
        lift = math.sin(t * math.pi) * H * 0.10
        return lerp(88, 52, t), lerp(104, 78, t), lift

    def leg_angles(p):
        """Knees stay planted; the thigh rocks as the hips travel over them."""
        t = math.sin(p * 2 * math.pi)
        return -30.0 + t * 9.0, -80.0 - t * 5.0

    # ---- far side first, dimmed, so it sits behind the body -------------
    fu, fl = leg_angles(far)
    canvas = _leg(canvas, parts, rig, hip, "far", fu, fl)

    su, sf, slift = arm_angles(far)
    canvas = draw_arm(canvas, (shoulder[0], shoulder[1] - slift),
                      su, sf, upper_len, fore_len, thickness * 0.94,
                      rig.cloth, rig.skin, dim=0.72)

    # ---- body -----------------------------------------------------------
    torso_img, _ = parts["torso"]
    canvas = paste_rotated(canvas, torso_img,
                           part_pivot(parts, "torso", (rig.hip_cx, rig.hip_y)),
                           torso_angle, hip)

    # ---- near side ------------------------------------------------------
    nu, nl = leg_angles(near)
    canvas = _leg(canvas, parts, rig, hip, "near", nu, nl)

    head_img, _ = parts["head"]
    canvas = paste_rotated(canvas, head_img,
                           part_pivot(parts, "head", (rig.head_cx, rig.neck_y)),
                           head_angle, neck)

    su, sf, slift = arm_angles(near)
    canvas = draw_arm(canvas, (shoulder[0], shoulder[1] - slift),
                      su, sf, upper_len, fore_len, thickness,
                      rig.cloth, rig.skin, dim=1.0)

    head_anchor = add(neck, rot_vec((0, rig.top - rig.neck_y), head_angle))

    shadow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    shadow = draw_shadow(shadow, (W * 0.5, ground + H * 0.02), H * 0.34, H * 0.045)
    canvas = Image.alpha_composite(shadow, canvas)

    return canvas, head_anchor


def _leg(canvas, parts, rig, hip, side: str, thigh_angle: float, shin_angle: float):
    dim_upper = f"leg_{'far' if side == 'far' else 'near'}_upper"
    dim_lower = f"leg_{'far' if side == 'far' else 'near'}_lower"

    thigh, _ = parts[dim_upper]
    shin, _ = parts[dim_lower]

    if side == "far":
        thigh = _dim(thigh, 0.78)
        shin = _dim(shin, 0.78)

    canvas = paste_rotated(canvas, thigh,
                           part_pivot(parts, dim_upper, (rig.hip_cx, rig.hip_y)),
                           thigh_angle, hip)

    knee = add(hip, rot_vec((0, rig.knee_y - rig.hip_y), thigh_angle))
    canvas = paste_rotated(canvas, shin,
                           part_pivot(parts, dim_lower, (rig.hip_cx, rig.knee_y)),
                           shin_angle, knee)
    return canvas


def _dim(img: Image.Image, factor: float) -> Image.Image:
    from PIL import ImageEnhance
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = ImageEnhance.Brightness(rgb).enhance(factor)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, a))


# --------------------------------------------------------------------------
# one play frame (sitting up, waving)
# --------------------------------------------------------------------------

def play_frame(parts, rig, canvas_size, phase: float):
    H = rig.bottom - rig.top
    W, Ch = canvas_size
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

    ground = Ch * 0.80
    wave = math.sin(phase * 2 * math.pi)
    bounce = abs(math.sin(phase * math.pi)) * H * 0.035

    torso_angle = -6.0 + wave * 5.0
    hip = (W * 0.5, ground - H * 0.06 + bounce * 0.4)

    neck = add(hip, rot_vec((rig.head_cx - rig.hip_cx, rig.neck_y - rig.hip_y), torso_angle))
    shoulder = add(hip, rot_vec((rig.shoulder_cx - rig.hip_cx, rig.shoulder_y - rig.hip_y),
                                torso_angle))
    head_angle = torso_angle * 0.6 + wave * 6.0

    upper_len = H * 0.24
    fore_len = H * 0.22
    thickness = max(4.0, H * 0.085)

    # legs folded underneath, kneeling
    canvas = _leg(canvas, parts, rig, hip, "far", 14.0, -78.0)
    canvas = draw_arm(canvas, shoulder, 118 + wave * 6, 150 + wave * 10,
                      upper_len, fore_len, thickness * 0.94,
                      rig.cloth, rig.skin, dim=0.72)

    torso_img, _ = parts["torso"]
    canvas = paste_rotated(canvas, torso_img,
                           part_pivot(parts, "torso", (rig.hip_cx, rig.hip_y)),
                           torso_angle, hip)

    canvas = _leg(canvas, parts, rig, hip, "near", 22.0, -70.0)

    head_img, _ = parts["head"]
    canvas = paste_rotated(canvas, head_img,
                           part_pivot(parts, "head", (rig.head_cx, rig.neck_y)),
                           head_angle, neck)

    # the near arm waves overhead
    canvas = draw_arm(canvas, shoulder, -58 + wave * 16, -96 + wave * 30,
                      upper_len, fore_len, thickness,
                      rig.cloth, rig.skin, dim=1.0)

    head_anchor = add(neck, rot_vec((0, rig.top - rig.neck_y), head_angle))

    shadow = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    shadow = draw_shadow(shadow, (W * 0.5, ground + H * 0.04), H * 0.24, H * 0.04)
    canvas = Image.alpha_composite(shadow, canvas)

    return canvas, head_anchor


# --------------------------------------------------------------------------

def build_figure(folder: Path, verbose: bool = True) -> dict:
    base_path = folder / "base.png"
    base = Image.open(base_path).convert("RGBA")
    rig = analyze(base)
    parts = slice_parts(base, rig)

    H = rig.bottom - rig.top
    canvas_size = (int(H * 1.5), int(H * 1.15))

    rendered: dict[str, list] = {}
    for name, fn, count in (("crawl", crawl_frame, CRAWL_FRAMES),
                            ("play", play_frame, PLAY_FRAMES)):
        frames = []
        for i in range(count):
            frames.append(fn(parts, rig, canvas_size, i / count))
        rendered[name] = frames

    # one shared crop across every frame of every animation, so the figure
    # never jitters when the animation changes and the feet always sit on the
    # bottom edge of the frame.
    boxes = [img.getbbox() for frames in rendered.values() for img, _ in frames
             if img.getbbox()]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)

    meta = {
        "name": folder.name,
        "frame_size": [x1 - x0, y1 - y0],
        "colors": {"skin": list(rig.skin), "cloth": list(rig.cloth)},
        "anims": {},
    }

    for name, frames in rendered.items():
        files, anchors = [], []
        for i, (img, anchor) in enumerate(frames):
            out = img.crop((x0, y0, x1, y1))
            fname = f"{name}_{i:03d}.png"
            out.save(folder / fname)
            files.append(fname)
            anchors.append([round(anchor[0] - x0, 1), round(anchor[1] - y0, 1)])
        meta["anims"][name] = {
            "fps": CRAWL_FPS if name == "crawl" else PLAY_FPS,
            "frames": files,
            "head": anchors,
        }

    save_meta(folder / "meta.json", meta)
    if verbose:
        print(f"  {folder.name}: {meta['frame_size'][0]}x{meta['frame_size'][1]}, "
              f"{sum(len(a['frames']) for a in meta['anims'].values())} frames, "
              f"skin={rig.skin} cloth={rig.cloth}")
    return meta


def clear_frames(folder: Path) -> None:
    """Delete previously generated frames so a rebuild cannot leave orphans."""
    for old in list(folder.glob("crawl_*.png")) + list(folder.glob("play_*.png")):
        old.unlink(missing_ok=True)
    (folder / "meta.json").unlink(missing_ok=True)


def build_all(folders, progress=None, verbose: bool = False) -> list[Path]:
    """Build frames for every folder, reporting progress and skipping failures.

    Returns the folders that built successfully.  ``progress`` is called as
    ``progress(fraction, message)``.
    """
    folders = list(folders)
    done: list[Path] = []
    errors: list[str] = []
    for i, folder in enumerate(folders):
        if progress:
            progress(i / max(1, len(folders)), f"animating {folder.name}")
        try:
            clear_frames(folder)
            build_figure(folder, verbose=verbose)
            done.append(folder)
        except Exception as exc:
            errors.append(f"{folder.name}: {exc}")
    if progress:
        progress(1.0, "done" if not errors else "; ".join(errors))
    if errors and not done:
        raise ValueError("; ".join(errors))
    return done
