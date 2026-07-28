"""Body-part extraction tests using a synthetic character image."""

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from desktop_pet.rig import extractor  # noqa: E402
from desktop_pet.rig.body_parts import STANDARD_PARTS  # noqa: E402


def synthetic_figure(size=(200, 400)):
    """Draw a simple stick/blob humanoid on a transparent canvas."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = size[0] // 2
    d.ellipse([cx - 30, 10, cx + 30, 70], fill=(255, 220, 180, 255))   # head
    d.rectangle([cx - 35, 70, cx + 35, 210], fill=(60, 120, 220, 255))  # torso
    d.rectangle([cx - 60, 80, cx - 35, 200], fill=(255, 220, 180, 255)) # left arm
    d.rectangle([cx + 35, 80, cx + 60, 200], fill=(255, 220, 180, 255)) # right arm
    d.rectangle([cx - 30, 210, cx - 5, 390], fill=(40, 40, 80, 255))    # left leg
    d.rectangle([cx + 5, 210, cx + 30, 390], fill=(40, 40, 80, 255))    # right leg
    return img


def test_content_bounding_box_trims_transparency():
    img = synthetic_figure()
    box = extractor.content_bounding_box(img)
    x0, y0, x1, y1 = box
    assert x0 > 0 and y0 >= 0
    assert y1 <= img.height
    assert (x1 - x0) < img.width  # trimmed horizontally


def test_auto_humanoid_extracts_the_core_parts():
    """Head, torso, hips and both legs are always cut.

    Arms are conditional by design: when they rest against the body they are
    already inside the torso crop, and slicing them out again produces
    duplicated limbs that flap about detached.
    """
    img = synthetic_figure()
    result = extractor.extract_auto_humanoid(img)
    for part in extractor.CORE_PARTS:
        assert part in result.parts, f"missing {part}"
        sprite = result.parts[part].image
        assert sprite.width > 0 and sprite.height > 0


def test_regions_extraction_roundtrip():
    img = synthetic_figure()
    regions = {
        "head": {"rect": [70, 10, 130, 70], "pivot": [0.5, 0.9]},
        "torso": {"rect": [65, 70, 135, 210], "pivot": [0.5, 0.05]},
    }
    result = extractor.extract_regions(img, regions)
    assert result.method == "regions"
    assert result.parts["head"].image.size == (60, 60)
    assert result.parts["torso"].source_rect == (65, 70, 135, 210)


def test_extract_dispatch_and_serialization():
    img = synthetic_figure()
    result = extractor.extract(img, method="auto_humanoid")
    as_regions = result.to_regions_dict()
    assert "head" in as_regions and "rect" in as_regions["head"]


def test_pose_method_falls_back_without_mediapipe():
    img = synthetic_figure()
    # mediapipe isn't installed in CI; this must not raise, just fall back.
    result = extractor.extract_with_pose(img)
    assert extractor.CORE_PARTS.issubset(result.parts.keys())


def test_save_and_load_parts(tmp_path):
    img = synthetic_figure()
    result = extractor.extract_auto_humanoid(img)
    paths = extractor.save_parts(result, str(tmp_path))
    assert paths
    loaded = extractor.load_parts_from_dir(str(tmp_path))
    assert "head" in loaded and loaded["head"].image is not None
