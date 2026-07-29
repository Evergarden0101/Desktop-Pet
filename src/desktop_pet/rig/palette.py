"""Sample a character's colours out of its source picture.

When a photo doesn't show usable arms or legs - folded arms, a shot cropped at
the thigh - the honest thing is to *draw* those limbs rather than carve them out
of whatever pixels happen to be there. For the drawn limbs to look like they
belong to the person in the photo, they need that person's colours: their skin
tone, the sleeve of the top they're wearing, the colour of their trousers.

This module pulls those colours straight from the image. Everything is a median
over a sampled region, which shrugs off highlights, shadows and JPEG noise far
better than a mean, and transparent pixels are ignored so a cut-out PNG doesn't
drag the colour toward its background.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

#: Fallbacks if a region can't be sampled (fully transparent, zero-size, ...).
_DEFAULTS: Dict[str, RGB] = {
    "skin": (238, 200, 170),
    "hair": (60, 45, 40),
    "top": (120, 140, 190),
    "sleeve": (120, 140, 190),
    "trouser": (60, 62, 84),
    "shoe": (38, 38, 48),
}


def _median_colour(image, box, alpha_min: int = 200, max_samples: int = 2000) -> Optional[RGB]:
    """Median RGB of the opaque pixels inside ``box``.

    The region is downsampled first, so this stays fast on large photos and the
    median is taken over a representative spread rather than every pixel.
    """
    left, top, right, bottom = (int(round(v)) for v in box)
    left = max(0, left)
    top = max(0, top)
    right = min(image.width, right)
    bottom = min(image.height, bottom)
    if right - left < 2 or bottom - top < 2:
        return None

    crop = image.convert("RGBA").crop((left, top, right, bottom))
    # Downsample to at most ~sqrt(max_samples) per side.
    side = max(1, int(max_samples ** 0.5))
    if crop.width > side or crop.height > side:
        crop = crop.resize(
            (min(side, crop.width), min(side, crop.height)),
            _resampling(),
        )

    reds: List[int] = []
    greens: List[int] = []
    blues: List[int] = []
    for r, g, b, a in _pixels(crop):
        if a >= alpha_min:
            reds.append(r)
            greens.append(g)
            blues.append(b)
    if len(reds) < 4:
        return None

    def median(values: Sequence[int]) -> int:
        ordered = sorted(values)
        return int(ordered[len(ordered) // 2])

    return (median(reds), median(greens), median(blues))


def _resampling():
    from PIL import Image

    # Pillow moved the enum in 9.1; support both.
    return getattr(getattr(Image, "Resampling", Image), "BILINEAR")


def _pixels(crop):
    """Every ``(r, g, b, a)`` tuple in ``crop``, across Pillow versions.

    ``getdata`` is deprecated from Pillow 14; ``get_flattened_data`` is its
    replacement and returns the same sequence of per-pixel tuples.
    """
    getter = getattr(crop, "get_flattened_data", None)  # Pillow >= 11.3
    return getter() if getter is not None else crop.getdata()


def _shade(colour: RGB, factor: float) -> RGB:
    return tuple(max(0, min(255, int(round(c * factor)))) for c in colour)  # type: ignore[return-value]


def to_hex(colour: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*colour)


def sample_character(image, shape, person=None) -> Dict[str, str]:
    """Return a hex palette describing the character in ``image``.

    ``shape`` is a :class:`~desktop_pet.rig.silhouette.Silhouette`; ``person``
    the optional detected landmarks, which pin down the face far more precisely
    than the bounding box can.
    """
    x0, y0, x1, y1 = shape.box
    width = max(1, x1 - x0)
    head_h = max(4, shape.shoulder_y - y0)
    centre = (x0 + x1) / 2.0

    out: Dict[str, RGB] = {}

    # ---- skin: the cheeks, which are large, flat and reliably lit ----------
    skin_box = None
    if person is not None:
        nose = person.point("nose")
        if nose is not None:
            span = head_h * 0.16
            skin_box = (nose[0] - span, nose[1] + span * 0.35,
                        nose[0] + span, nose[1] + span * 1.5)
    if skin_box is None:
        # Middle of the head, below the eye line.
        skin_box = (centre - head_h * 0.18, y0 + head_h * 0.55,
                    centre + head_h * 0.18, y0 + head_h * 0.85)
    out["skin"] = _median_colour(image, skin_box) or _DEFAULTS["skin"]

    # ---- hair: the crown -------------------------------------------------
    out["hair"] = _median_colour(
        image, (centre - head_h * 0.25, y0 + head_h * 0.04,
                centre + head_h * 0.25, y0 + head_h * 0.22)
    ) or _DEFAULTS["hair"]

    # ---- top: the middle of the chest ------------------------------------
    chest_y = shape.shoulder_y + (shape.hip_y - shape.shoulder_y) * 0.35
    out["top"] = _median_colour(
        image, (centre - width * 0.12, chest_y - head_h * 0.12,
                centre + width * 0.12, chest_y + head_h * 0.12)
    ) or _DEFAULTS["top"]

    # ---- sleeve: the upper arm, halfway between shoulder and elbow ---------
    # That midpoint is squarely on the garment (or on bare skin, if the top is
    # sleeveless - either way it is the right colour for a drawn arm). The
    # elbow itself is a poor sample: on folded arms it lands out beyond the
    # body, where the nearest opaque pixels may be somebody's else's.
    sleeve = None
    if person is not None:
        for shoulder_name, elbow_name in (("shoulder_l", "elbow_l"), ("shoulder_r", "elbow_r")):
            shoulder = person.point(shoulder_name)
            elbow = person.point(elbow_name)
            if shoulder is None or elbow is None:
                continue
            mid = ((shoulder[0] + elbow[0]) / 2.0, (shoulder[1] + elbow[1]) / 2.0)
            span = head_h * 0.11
            sleeve = _median_colour(
                image, (mid[0] - span, mid[1] - span, mid[0] + span, mid[1] + span)
            )
            if sleeve is not None:
                break
    if sleeve is None:
        left, right = shape.span_at(int(chest_y))
        edge = max(6.0, (right - left) * 0.10)
        sleeve = _median_colour(image, (left, chest_y - edge, left + edge * 2, chest_y + edge))
    out["sleeve"] = sleeve or out["top"]

    # ---- trousers: just below the hips -----------------------------------
    trouser = None
    if shape.crotch_y < y1 - 4:
        band_top = shape.crotch_y + (y1 - shape.crotch_y) * 0.15
        band_bottom = min(y1 - 2, band_top + max(6.0, (y1 - shape.crotch_y) * 0.35))
        trouser = _median_colour(
            image, (centre - width * 0.16, band_top, centre + width * 0.16, band_bottom)
        )
    out["trouser"] = trouser or _shade(out["top"], 0.55)

    # ---- shoes: the very bottom, else a darker trouser --------------------
    shoe = None
    if y1 - shape.foot_top > 4:
        shoe = _median_colour(
            image, (centre - width * 0.20, shape.foot_top, centre + width * 0.20, y1 - 1)
        )
    out["shoe"] = shoe or _shade(out["trouser"], 0.7)

    return {key: to_hex(value) for key, value in out.items()}


def limb_palette(colours: Dict[str, str]) -> Dict[str, str]:
    """Map sampled colours onto the rig's part names."""
    skin = colours.get("skin", to_hex(_DEFAULTS["skin"]))
    sleeve = colours.get("sleeve", colours.get("top", to_hex(_DEFAULTS["top"])))
    trouser = colours.get("trouser", to_hex(_DEFAULTS["trouser"]))
    shoe = colours.get("shoe", to_hex(_DEFAULTS["shoe"]))
    return {
        "upper_arm_l": sleeve, "upper_arm_r": sleeve,
        # Forearms are bare below a short sleeve, but for a long-sleeved top
        # the sleeve colour is right; sampling near the elbow already picked
        # whichever it is, so reuse it and leave only the hands as skin.
        "forearm_l": sleeve, "forearm_r": sleeve,
        "hand_l": skin, "hand_r": skin,
        "thigh_l": trouser, "thigh_r": trouser,
        "shin_l": trouser, "shin_r": trouser,
        "foot_l": shoe, "foot_r": shoe,
        "hips": trouser,
        "torso": colours.get("top", to_hex(_DEFAULTS["top"])),
        "head": skin,
    }
