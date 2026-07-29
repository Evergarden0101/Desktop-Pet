"""Tests for content-aware silhouette analysis and the extraction it drives."""

from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from desktop_pet.rig import extractor, silhouette  # noqa: E402
from desktop_pet.rig.body_parts import STANDARD_PARTS  # noqa: E402


def tall_figure(W=240, H=560):
    """Realistic adult proportions with arms resting against the body."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2
    d.ellipse([cx - 34, 20, cx + 34, 92], fill=(255, 217, 160, 255))       # head
    d.rectangle([cx - 12, 88, cx + 12, 108], fill=(255, 217, 160, 255))    # neck
    d.rounded_rectangle([cx - 52, 105, cx + 52, 260], 16, fill=(79, 140, 255, 255))
    d.rounded_rectangle([cx - 46, 255, cx + 46, 310], 12, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx - 78, 115, cx - 40, 265], 12, fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx + 40, 115, cx + 78, 265], 12, fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx - 42, 305, cx - 8, 505], 12, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx + 8, 305, cx + 42, 505], 12, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx - 48, 500, cx - 4, 540], 8, fill=(31, 34, 51, 255))
    d.rounded_rectangle([cx + 4, 500, cx + 48, 540], 8, fill=(31, 34, 51, 255))
    return img


def chibi_figure(W=260, H=340):
    """Huge head - fixed proportion bands would slice it in half."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2
    d.ellipse([cx - 70, 10, cx + 70, 150], fill=(255, 224, 189, 255))
    d.rectangle([cx - 14, 145, cx + 14, 160], fill=(255, 224, 189, 255))
    d.rounded_rectangle([cx - 44, 158, cx + 44, 244], 16, fill=(255, 140, 170, 255))
    d.rounded_rectangle([cx - 36, 240, cx - 6, 320], 10, fill=(120, 90, 200, 255))
    d.rounded_rectangle([cx + 6, 240, cx + 36, 320], 10, fill=(120, 90, 200, 255))
    return img


def arms_out_figure(W=340, H=520):
    """Arms held away from the torso, leaving a visible gap on each side."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2
    d.ellipse([cx - 38, 14, cx + 38, 92], fill=(255, 217, 160, 255))
    d.rectangle([cx - 13, 88, cx + 13, 106], fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx - 50, 104, cx + 50, 250], 16, fill=(90, 200, 140, 255))
    d.rounded_rectangle([cx - 46, 246, cx + 46, 300], 12, fill=(50, 60, 90, 255))
    d.rounded_rectangle([cx - 120, 120, cx - 72, 250], 14, fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx + 72, 120, cx + 120, 250], 14, fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx - 40, 296, cx - 8, 470], 12, fill=(50, 60, 90, 255))
    d.rounded_rectangle([cx + 8, 296, cx + 40, 470], 12, fill=(50, 60, 90, 255))
    return img


# ------------------------------------------------------------------ analysis
def test_finds_neck_below_the_head():
    img = tall_figure()
    shape = silhouette.analyze(img)
    assert shape.confident
    # The head spans y=20..92 and the neck pinch is right below it.
    assert 85 <= shape.neck_y <= 115
    assert shape.shoulder_y > shape.neck_y


def test_finds_neck_on_a_big_headed_chibi():
    """The whole point: landmarks follow the drawing, not fixed fractions."""
    img = chibi_figure()
    shape = silhouette.analyze(img)
    assert shape.confident
    # Head reaches y=150, so the neck must be near there - not at ~13% of height.
    assert 135 <= shape.neck_y <= 170


def test_detects_leg_split():
    img = tall_figure()
    shape = silhouette.analyze(img)
    # Legs part around the image centre.
    assert abs(shape.leg_split_x - img.width / 2) < 25
    assert shape.crotch_y > shape.hip_y


def test_detects_detached_arms():
    assert silhouette.analyze(arms_out_figure()).arms_detached
    assert not silhouette.analyze(tall_figure()).arms_detached


def test_arms_only_extracted_when_separable():
    """Arms resting on the body are drawn, never sliced off the torso."""
    detached = extractor.extract_auto_humanoid(arms_out_figure())
    assert "upper_arm_l" in detached.parts
    assert any(b["name"] == "upper_arm_l" for b in detached.skeleton)

    against = extractor.extract_auto_humanoid(tall_figure())
    assert "upper_arm_l" not in against.parts   # no strip cut off the torso
    assert "torso" in against.parts
    # ...but the bone still exists, painted in a colour taken from the picture,
    # so the pet can reach for ledges and wave.
    assert against.layout == "hybrid"
    assert any(b["name"] == "upper_arm_l" for b in against.skeleton)
    assert against.palette.get("upper_arm_l")
    assert against.limb_radii.get("upper_arm_l", 0) > 0


def test_drawn_arms_do_not_replace_real_legs():
    """A drawing whose legs are visible keeps them cut from the art."""
    result = extractor.extract_auto_humanoid(tall_figure())
    for part in ("thigh_l", "shin_r", "foot_l", "hips"):
        assert part in result.parts, part


def test_landmarks_are_ordered_top_to_bottom():
    for figure in (tall_figure(), chibi_figure(), arms_out_figure()):
        s = silhouette.analyze(figure)
        assert s.head_top <= s.neck_y <= s.shoulder_y
        assert s.shoulder_y <= s.hip_y <= s.crotch_y
        assert s.crotch_y <= s.foot_top <= s.bottom


def test_blob_becomes_a_cutout():
    """A ball has no legs to rig, so keep it whole rather than inventing limbs."""
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([20, 20, 180, 180], fill=(200, 120, 255, 255))
    shape = silhouette.analyze(img)
    assert shape.layout == "cutout"

    result = extractor.extract_auto_humanoid(img)
    assert "torso" in result.parts and "head" in result.parts
    assert result.layout == "cutout"


# ---------------------------------------------------------------- extraction
@pytest.mark.parametrize(
    "factory", [tall_figure, chibi_figure, arms_out_figure], ids=["tall", "chibi", "arms"]
)
def test_extraction_produces_sane_boxes(factory):
    img = factory()
    result = extractor.extract_auto_humanoid(img)
    # Body and legs are always cut; arms only when they are separable from the
    # torso (otherwise they stay part of the torso sprite by design).
    core = {"head", "torso", "hips", "thigh_l", "shin_l", "foot_l",
            "thigh_r", "shin_r", "foot_r"}
    assert core.issubset(result.parts.keys())

    x0, y0, x1, y1 = result.content_box
    for name, part in result.parts.items():
        rect = part.source_rect
        assert rect is not None, name
        left, top, right, bottom = rect
        assert right > left and bottom > top, f"{name} is empty"
        # Every cut must lie inside the figure's bounding box.
        assert left >= x0 - 3 and right <= x1 + 3, f"{name} escapes horizontally"
        assert top >= y0 - 3 and bottom <= y1 + 3, f"{name} escapes vertically"


def test_head_box_covers_the_whole_head():
    """The old band slicing cut chibi heads in half; this must not."""
    img = chibi_figure()
    result = extractor.extract_auto_humanoid(img)
    left, top, right, bottom = result.parts["head"].source_rect
    # The drawn head is the ellipse y=10..150, x=60..200.
    assert top <= 14
    assert bottom >= 145
    assert right - left >= 130


def test_legs_are_not_inflated_by_outstretched_arms():
    img = arms_out_figure()
    result = extractor.extract_auto_humanoid(img)
    thigh = result.parts["thigh_l"].source_rect
    torso = result.parts["torso"].source_rect
    thigh_width = thigh[2] - thigh[0]
    torso_width = torso[2] - torso[0]
    # A leg should be narrower than the torso, never as wide as the arm span.
    assert thigh_width < torso_width


def test_legs_split_into_left_and_right():
    result = extractor.extract_auto_humanoid(tall_figure())
    left = result.parts["thigh_l"].source_rect
    right = result.parts["thigh_r"].source_rect
    assert left[2] <= right[0] + 2  # left ends where right begins


# --------------------------------------------------------------- sprite axes
def test_sprite_axes_follow_their_bone_direction():
    """Up-the-body parts run bottom-to-top; limbs run top-to-bottom.

    ``head``, ``torso`` and ``hips`` all hang off bones that point upward, so
    their joint is at the sprite's lower edge. Getting this wrong collapses the
    pivot onto the anchor and the part is scaled by a huge factor.
    """
    for part in ("head", "torso", "hips"):
        pivot, anchor = extractor.part_axis(part)
        assert pivot[1] > anchor[1], f"{part} sprite must run bottom-to-top"
        assert abs(pivot[1] - anchor[1]) > 0.5, f"{part} axis is degenerate"
    for part in ("thigh_l", "forearm_r", "shin_r"):
        pivot, anchor = extractor.part_axis(part)
        assert pivot[1] < anchor[1], f"{part} sprite should run top-to-bottom"
        assert abs(pivot[1] - anchor[1]) > 0.5, f"{part} axis is degenerate"


def test_extracted_axes_span_the_sprite():
    """Every part's measured axis must be a real length, not a few pixels."""
    result = extractor.extract_auto_humanoid(tall_figure())
    for name, part in result.parts.items():
        span = abs(part.child_anchor.y - part.pivot.y) * part.size[1]
        assert span > part.size[1] * 0.4, f"{name} axis collapsed ({span:.1f}px)"


def test_extracted_parts_carry_their_axes():
    result = extractor.extract_auto_humanoid(tall_figure())
    head = result.parts["head"]
    assert head.pivot.y > head.child_anchor.y
    thigh = result.parts["thigh_l"]
    assert thigh.pivot.y < thigh.child_anchor.y


def test_regions_roundtrip_preserves_axes():
    img = tall_figure()
    result = extractor.extract_auto_humanoid(img)
    regions = result.to_regions_dict()
    assert "anchor" in regions["head"]

    again = extractor.extract_regions(img, regions)
    assert again.parts["head"].child_anchor.y == pytest.approx(
        result.parts["head"].child_anchor.y, abs=1e-3
    )


# ------------------------------------------------------- derived proportions
def test_derived_skeleton_matches_the_artwork():
    """An imported character keeps its own build instead of a preset one."""
    chibi = extractor.extract_auto_humanoid(chibi_figure()).skeleton
    tall = extractor.extract_auto_humanoid(tall_figure()).skeleton
    assert chibi and tall

    def ratio(bones):
        by_name = {b["name"]: b["length"] for b in bones}
        return by_name["head"] / by_name["thigh_l"]

    # The chibi's head is large relative to its legs; the tall figure's isn't.
    assert ratio(chibi) > ratio(tall)


def test_derived_skeleton_is_complete_and_positive():
    bones = extractor.extract_auto_humanoid(tall_figure()).skeleton
    names = {b["name"] for b in bones}
    assert extractor.CORE_PARTS.issubset(names)
    for bone in bones:
        assert bone["length"] > 0, bone["name"]
        assert "rest_angle" in bone and "parent" in bone
