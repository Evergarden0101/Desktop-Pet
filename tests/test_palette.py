"""Colour sampling for drawn limbs, and the decision to draw them at all.

None of this needs the pose model: the palette reads pixels, and the limb plan
reads landmarks that the tests supply directly.
"""

from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from desktop_pet.rig import extractor, palette, silhouette  # noqa: E402

SKIN = (238, 200, 170, 255)
SHIRT = (40, 90, 200, 255)
JEAN = (30, 34, 60, 255)
SHOE = (20, 20, 24, 255)
HAIR = (70, 45, 30, 255)


def dressed_figure(W=300, H=800):
    """A figure with a clearly different colour for each garment."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2
    d.ellipse([cx - 60, 15, cx + 60, 165], fill=HAIR)
    d.ellipse([cx - 44, 45, cx + 44, 155], fill=SKIN)
    d.rectangle([cx - 18, 145, cx + 18, 180], fill=SKIN)
    d.rounded_rectangle([cx - 90, 178, cx + 90, 430], 26, fill=SHIRT)
    d.rounded_rectangle([cx - 84, 425, cx + 84, 490], 18, fill=JEAN)
    d.rounded_rectangle([cx - 78, 485, cx - 8, 720], 20, fill=JEAN)
    d.rounded_rectangle([cx + 8, 485, cx + 78, 720], 20, fill=JEAN)
    d.rounded_rectangle([cx - 84, 710, cx - 4, 780], 12, fill=SHOE)
    d.rounded_rectangle([cx + 4, 710, cx + 84, 780], 12, fill=SHOE)
    return img


def near(hex_colour: str, rgb, tolerance: int = 45) -> bool:
    got = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= tolerance for a, b in zip(got, rgb[:3]))


# --------------------------------------------------------------- sampling
def test_samples_each_garment_from_the_picture():
    img = dressed_figure()
    shape = silhouette.analyze(img)
    colours = palette.sample_character(img, shape)

    assert near(colours["skin"], SKIN), colours["skin"]
    assert near(colours["top"], SHIRT), colours["top"]
    assert near(colours["trouser"], JEAN), colours["trouser"]


def test_transparent_pixels_do_not_drag_the_colour():
    """A cut-out PNG must not sample its own empty background."""
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([40, 40, 80, 80], fill=(200, 60, 60, 255))
    got = palette._median_colour(img, (0, 0, 120, 120))
    assert got == (200, 60, 60)


def test_unsampleable_region_falls_back_rather_than_failing():
    img = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
    assert palette._median_colour(img, (0, 0, 60, 60)) is None
    assert palette._median_colour(img, (10, 10, 10, 10)) is None


def test_limb_palette_covers_every_drawable_part():
    mapped = palette.limb_palette({"skin": "#112233", "top": "#445566"})
    for part in ("upper_arm_l", "forearm_r", "hand_l", "thigh_r", "shin_l",
                 "foot_r", "hips", "torso", "head"):
        assert mapped[part].startswith("#") and len(mapped[part]) == 7, part


# -------------------------------------------------------------- limb plan
class _Shape:
    """The handful of fields :func:`_limb_plan` looks at."""

    def __init__(self, source="outline", layout="figure",
                 legs_detected=True, arms_detached=True):
        self.source = source
        self.layout = layout
        self.legs_detected = legs_detected
        self.arms_detached = arms_detached


def test_a_blob_is_never_given_human_limbs():
    plan = extractor._limb_plan(_Shape(layout="cutout", legs_detected=False,
                                       arms_detached=False))
    assert plan == (False, False)


def test_a_detected_person_without_legs_gets_them_drawn():
    plan = extractor._limb_plan(_Shape(source="pose", layout="cutout",
                                       legs_detected=False, arms_detached=False))
    assert plan == (True, True)


def test_a_drawing_keeps_its_own_legs():
    """Without a detector, "no leg split" means pressed together, not absent."""
    plan = extractor._limb_plan(_Shape(legs_detected=False, arms_detached=False))
    assert plan == (True, False)


def test_separable_arms_and_legs_are_cut_not_drawn():
    assert extractor._limb_plan(_Shape(source="pose")) == (False, False)
    assert extractor._limb_plan(_Shape()) == (False, False)


# ------------------------------------------------------------ proportions
def test_limb_unit_prefers_the_torso_over_a_hair_inflated_head():
    """A portrait's head crop is huge; limbs quoted in it put the pet on stilts."""
    img = dressed_figure()
    shape = silhouette.analyze(img)
    shape.source = "pose"
    # Pretend the picture is a close-up: a head crop twice its honest size.
    shape.neck_y = shape.box[1] + (shape.shoulder_y - shape.box[1]) * 2
    unit = extractor._limb_unit(shape)
    assert unit <= (shape.hip_y - shape.shoulder_y) / extractor.TORSO_HEADS + 1


def test_hybrid_rig_has_every_bone_and_only_the_cut_parts():
    img = dressed_figure()
    shape = silhouette.analyze(img)
    bones = {b["name"]: b for b in extractor.hybrid_skeleton(shape, True, True)}
    assert len(bones) == 15
    assert all(b["length"] > 0 for b in bones.values())

    regions = extractor.hybrid_regions(shape, draw_arms=True, draw_legs=True)
    assert set(regions) == {"head", "torso"}

    # With real legs in the picture they are cut, not drawn.
    regions = extractor.hybrid_regions(shape, draw_arms=True, draw_legs=False)
    assert {"head", "torso", "hips", "thigh_l", "shin_r", "foot_l"} <= set(regions)
    assert "upper_arm_l" not in regions


def test_drawn_limbs_are_slimmer_than_the_body():
    img = dressed_figure()
    shape = silhouette.analyze(img)
    radii = extractor.limb_radii_for(shape)
    assert radii["thigh_l"] > radii["shin_l"] > 0
    assert radii["upper_arm_l"] > radii["forearm_l"] > 0
    assert radii["hips"] > radii["thigh_l"]
    offsets = extractor.joint_offsets_for(shape)
    assert offsets["torso"] > offsets["hips"] > 0


def test_hybrid_rig_is_normalised_to_the_standard_height():
    """A waist-up photo's drawn legs are height its crop never contained.

    Scaling by the crop would make that pet twice as tall as everyone else at
    the same user scale setting, so the *finished rig* is what gets normalised.
    """
    img = dressed_figure()
    shape = silhouette.analyze(img)
    for draw_arms, draw_legs in ((True, True), (True, False), (False, True)):
        bones = {b["name"]: b["length"]
                 for b in extractor.hybrid_skeleton(shape, draw_arms, draw_legs)}
        standing = sum(bones[n] for n in
                       ("head", "torso", "hips", "thigh_l", "shin_l", "foot_l"))
        assert standing == pytest.approx(extractor.RIG_HEIGHT, abs=0.5), (
            draw_arms, draw_legs, standing)


def test_radii_follow_the_rig_not_the_crop():
    """Thickness must use the same unit as the bones, or limbs come out fat."""
    img = dressed_figure()
    shape = silhouette.analyze(img)
    unit = extractor.hybrid_unit(shape, True, True)
    radii = extractor.limb_radii_for(shape, unit)
    bones = {b["name"]: b["length"] for b in extractor.hybrid_skeleton(shape, True, True)}
    # A thigh is a limb, not a barrel: much longer than it is wide.
    assert bones["thigh_l"] > radii["thigh_l"] * 2
    assert bones["upper_arm_l"] > radii["upper_arm_l"] * 2
