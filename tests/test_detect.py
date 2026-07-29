"""Pose-detection tests.

The detector is optional, so these skip cleanly when MediaPipe (or its model)
isn't present. The parts that don't need the model - graceful degradation,
landmark bookkeeping, layout decisions - always run.
"""

from __future__ import annotations

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from desktop_pet.rig import detect, extractor, silhouette  # noqa: E402

pose_available = pytest.mark.skipif(
    not detect.available(download=False),
    reason="MediaPipe pose model not available",
)


# ------------------------------------------------------- graceful degradation
def test_detect_returns_none_without_a_detector(monkeypatch):
    """A missing library or model must degrade, never raise."""
    monkeypatch.setattr(detect, "_get_detector", lambda: None)
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    assert detect.detect_person(img) is None


def test_detect_swallows_detector_errors(monkeypatch):
    class Boom:
        def detect(self, *_a, **_k):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(detect, "_get_detector", lambda: Boom())
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    assert detect.detect_person(img) is None


def test_ensure_model_does_not_download_when_asked_not_to(monkeypatch, tmp_path):
    monkeypatch.setattr(detect, "model_dir", lambda: str(tmp_path))
    monkeypatch.setattr(detect, "model_path", lambda: str(tmp_path / "absent.task"))
    assert detect.ensure_model(download=False) is None


def test_extraction_still_works_without_a_detector(monkeypatch):
    """Silhouette analysis must remain the fallback path."""
    monkeypatch.setattr(detect, "_get_detector", lambda: None)
    img = Image.new("RGBA", (200, 460), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = 100
    d.ellipse([cx - 30, 16, cx + 30, 78], fill=(255, 217, 160, 255))
    d.rectangle([cx - 10, 74, cx + 10, 92], fill=(255, 217, 160, 255))
    d.rounded_rectangle([cx - 44, 90, cx + 44, 220], 14, fill=(79, 140, 255, 255))
    d.rounded_rectangle([cx - 40, 216, cx + 40, 258], 10, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx - 36, 256, cx - 6, 430], 10, fill=(47, 53, 80, 255))
    d.rounded_rectangle([cx + 6, 256, cx + 36, 430], 10, fill=(47, 53, 80, 255))

    result = extractor.extract_auto_humanoid(img)
    assert result.detector == "outline"
    assert extractor.CORE_PARTS.issubset(result.parts.keys())


# ----------------------------------------------------------------- landmarks
def test_person_helpers():
    person = detect.Person(
        points={"shoulder_l": (10.0, 100.0), "shoulder_r": (30.0, 120.0)},
        visibility={"shoulder_l": 0.9, "shoulder_r": 0.8, "knee_l": 0.1},
        image_size=(100, 200),
    )
    assert person.has("shoulder_l", "shoulder_r")
    assert not person.has("knee_l")           # below the visibility threshold
    assert not person.has("ankle_l")          # absent entirely
    assert person.mid("shoulder_l", "shoulder_r") == (20.0, 110.0)
    assert person.mid_y("shoulder_l", "shoulder_r") == 110.0
    assert person.mid("shoulder_l", "nose") is None


def test_from_person_needs_shoulders():
    img = Image.new("RGBA", (100, 200), (255, 255, 255, 255))
    person = detect.Person(points={"nose": (50.0, 20.0)}, visibility={"nose": 1.0})
    assert silhouette.from_person(img, person) is None


def test_from_person_head_runs_to_the_shoulders():
    """The head must span hair-to-shoulders, not stop at the face.

    Regression for imported photos coming out with half a face: the model
    locates the *face*, but hair above and around it is part of the character.
    """
    img = Image.new("RGBA", (200, 600), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([40, 0, 160, 599], fill=(200, 180, 160, 255))

    person = detect.Person(
        points={
            "nose": (100.0, 90.0),
            "shoulder_l": (60.0, 200.0), "shoulder_r": (140.0, 200.0),
            "hip_l": (70.0, 330.0), "hip_r": (130.0, 330.0),
            "knee_l": (75.0, 450.0), "knee_r": (125.0, 450.0),
            "ankle_l": (75.0, 560.0), "ankle_r": (125.0, 560.0),
        },
        visibility={k: 0.95 for k in (
            "nose", "shoulder_l", "shoulder_r", "hip_l", "hip_r",
            "knee_l", "knee_r", "ankle_l", "ankle_r")},
        image_size=(200, 600),
    )
    shape = silhouette.from_person(img, person)
    assert shape is not None
    assert shape.source == "pose"
    assert shape.head_top == 0
    # The head reaches down to the shoulders, well past the nose.
    assert shape.shoulder_y == 200
    assert shape.neck_y > 150
    assert shape.layout == "figure"
    assert shape.hip_y == 330

    # And the cut head box actually contains the face.
    regions = extractor.regions_from_silhouette(shape)
    top, bottom = regions["head"]["rect"][1], regions["head"]["rect"][3]
    assert top <= 0 and bottom >= 90, "head crop must contain the face"


def test_from_person_marks_a_bust_as_cutout():
    """Legs out of frame (low visibility) must not be invented."""
    img = Image.new("RGBA", (200, 300), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle([30, 0, 170, 299], fill=(180, 160, 200, 255))

    person = detect.Person(
        points={
            "nose": (100.0, 70.0),
            "shoulder_l": (55.0, 170.0), "shoulder_r": (145.0, 170.0),
            "hip_l": (75.0, 330.0), "hip_r": (125.0, 330.0),
            "knee_l": (80.0, 470.0), "knee_r": (120.0, 470.0),
        },
        visibility={
            "nose": 0.99, "shoulder_l": 0.98, "shoulder_r": 0.98,
            "hip_l": 0.2, "hip_r": 0.2, "knee_l": 0.02, "knee_r": 0.02,
        },
        image_size=(200, 300),
    )
    shape = silhouette.from_person(img, person)
    assert shape is not None
    assert shape.layout == "cutout"
    assert not shape.legs_detected


# ------------------------------------------------------- with the real model
@pose_available
def test_detector_finds_a_person_in_a_photograph():
    skimage = pytest.importorskip("skimage")
    from skimage import data

    photo = Image.fromarray(data.astronaut()).convert("RGBA")
    person = detect.detect_person(photo)
    assert person is not None
    assert person.has("shoulder_l", "shoulder_r")

    # The shoulders must land below the face, which is the whole point.
    nose_y = person.y("nose")
    shoulder_y = person.mid_y("shoulder_l", "shoulder_r")
    assert nose_y is not None and shoulder_y is not None
    assert shoulder_y > nose_y + 20


@pose_available
def test_photo_head_crop_contains_the_whole_face():
    """End-to-end: the old outline path cut this photo through the eyebrows."""
    skimage = pytest.importorskip("skimage")
    from skimage import data

    photo = Image.fromarray(data.astronaut()).convert("RGBA")
    result = extractor.extract_auto_humanoid(photo)
    assert result.detector == "pose"

    top, bottom = result.parts["head"].source_rect[1], result.parts["head"].source_rect[3]
    # The face occupies roughly y=100..200 in this 512px-tall photo.
    assert top <= 100
    assert bottom >= 200, "head crop cuts through the face"
