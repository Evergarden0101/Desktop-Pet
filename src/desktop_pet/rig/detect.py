"""Human detection for character import, using an open-source pose model.

Silhouette analysis (:mod:`desktop_pet.rig.silhouette`) reads the *outline* of a
picture. That works well for clean artwork, but on photographs it can be fooled
badly: long hair falling past the jaw makes the widest point of the upper body
sit inside the hair rather than at the shoulders, so the "head" ends up half a
face tall and the crop slices the face in two.

This module asks a real model instead. It uses **MediaPipe Pose** (Apache-2.0,
Google) via the Tasks API, which returns 33 body landmarks with per-point
visibility scores - so we learn not only where the shoulders, hips, knees and
ankles are, but whether they are in frame at all.

Everything here is optional and degrades quietly:

* MediaPipe missing        -> :func:`detect_person` returns ``None``
* model not downloaded yet -> fetched once into the user config dir, or ``None``
                              if there's no network
* nothing recognised       -> ``None``

Callers fall back to silhouette analysis, so import always works.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

#: Landmark indices we care about, from the MediaPipe Pose topology.
#: https://developers.google.com/mediapipe/solutions/vision/pose_landmarker
LANDMARKS = {
    "nose": 0,
    "eye_l": 2, "eye_r": 5,
    "ear_l": 7, "ear_r": 8,
    "mouth_l": 9, "mouth_r": 10,
    "shoulder_l": 11, "shoulder_r": 12,
    "elbow_l": 13, "elbow_r": 14,
    "wrist_l": 15, "wrist_r": 16,
    "hip_l": 23, "hip_r": 24,
    "knee_l": 25, "knee_r": 26,
    "ankle_l": 27, "ankle_r": 28,
    "heel_l": 29, "heel_r": 30,
    "foot_l": 31, "foot_r": 32,
}

#: Below this visibility a landmark is treated as not actually in the picture.
VISIBLE = 0.5

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)
_MODEL_NAME = "pose_landmarker_lite.task"
_download_lock = threading.Lock()


#: Segmentation confidences below/above which a pixel is definitely background
#: or definitely the person; in between the alpha ramps, which keeps hair and
#: shoulders from turning into a staircase of hard pixels.
_MASK_LO = 0.35
_MASK_HI = 0.65


@dataclass
class Person:
    """Detected body landmarks, in *pixel* coordinates of the source image."""

    points: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    visibility: Dict[str, float] = field(default_factory=dict)
    image_size: Tuple[int, int] = (0, 0)
    #: Per-pixel "this is the person" confidence as a PIL ``L`` image the same
    #: size as the source, or ``None`` when the model didn't produce one.
    mask: Optional[object] = None

    def has(self, *names: str, threshold: float = VISIBLE) -> bool:
        """True when every named landmark was detected and is in frame."""
        return all(self.visibility.get(n, 0.0) >= threshold for n in names)

    def point(self, name: str) -> Optional[Tuple[float, float]]:
        return self.points.get(name)

    def mid(self, a: str, b: str) -> Optional[Tuple[float, float]]:
        """Midpoint of two landmarks, if both were found."""
        pa, pb = self.points.get(a), self.points.get(b)
        if pa is None or pb is None:
            return None
        return ((pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0)

    def y(self, name: str) -> Optional[float]:
        p = self.points.get(name)
        return None if p is None else p[1]

    def mid_y(self, a: str, b: str) -> Optional[float]:
        m = self.mid(a, b)
        return None if m is None else m[1]


# --------------------------------------------------------------------- model
def model_dir() -> str:
    from ..config import config_dir

    path = os.path.join(config_dir(), "models")
    os.makedirs(path, exist_ok=True)
    return path


def model_path() -> str:
    return os.path.join(model_dir(), _MODEL_NAME)


def model_available() -> bool:
    return os.path.exists(model_path())


def ensure_model(download: bool = True, timeout: float = 30.0) -> Optional[str]:
    """Return the local model path, fetching it once if needed.

    Returns ``None`` when the model isn't present and can't be downloaded, so
    the caller can fall back rather than fail.
    """
    path = model_path()
    if os.path.exists(path):
        return path
    if not download:
        return None

    with _download_lock:
        if os.path.exists(path):  # another thread won the race
            return path
        try:
            import urllib.request

            tmp = path + ".part"
            with urllib.request.urlopen(_MODEL_URL, timeout=timeout) as response:
                data = response.read()
            if len(data) < 100_000:  # a truncated/error body, not a model
                return None
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
            return path
        except Exception:
            return None


def available(download: bool = False) -> bool:
    """Whether pose detection can run right now (library + model present)."""
    if stage() == STAGE_OFF:
        return False
    try:
        import mediapipe  # noqa: F401
    except Exception:
        return False
    return ensure_model(download=download) is not None


# ------------------------------------------------------- crash-safe staging
#
# MediaPipe is a native library. When it is unhappy - a graph it can't build, a
# model asset it can't read, an op missing from a frozen bundle - it does not
# raise: its C++ CHECK macros call abort(), which takes the whole application
# with them. No try/except in this file can catch that, so the only way to stop
# a bad import from killing the app *again* is to notice that it happened and
# ask for less next time.
#
# Each level below is one step less native work than the last.
STAGE_FULL = "full"            # landmarks + person segmentation
STAGE_LANDMARKS = "landmarks"  # landmarks only, no segmentation mask
STAGE_OFF = "off"              # don't load the model at all
_STAGES = (STAGE_FULL, STAGE_LANDMARKS, STAGE_OFF)

STAGE_LABELS = {
    STAGE_FULL: "person detection with background removal",
    STAGE_LANDMARKS: "person detection (no background removal)",
    STAGE_OFF: "disabled - silhouette analysis only",
}

_ENV_OVERRIDE = "DESKTOP_PET_DETECTOR"
_stage: Optional[str] = None
_stage_reason = ""


def _state_path() -> str:
    return os.path.join(model_dir(), "detector.json")


def _marker_path() -> str:
    """Exists only while a native call is in flight; survives an abort."""
    return os.path.join(model_dir(), "detector.running")


def _read_state() -> dict:
    try:
        import json

        with open(_state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(value: str, reason: str) -> None:
    try:
        import json

        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump({"stage": value, "reason": reason}, fh)
    except Exception:
        pass


def stage() -> str:
    """The detector level to use, demoting once if the last run never finished.

    A leftover marker file means the previous attempt entered native code and
    never came back - the process died inside MediaPipe. Rather than repeat it,
    drop to the next level down and record why.
    """
    global _stage, _stage_reason
    if _stage is not None:
        return _stage

    override = os.environ.get(_ENV_OVERRIDE, "").strip().lower()
    if override in _STAGES:
        _stage, _stage_reason = override, f"{_ENV_OVERRIDE} is set"
        return _stage

    state = _read_state()
    value = state.get("stage")
    _stage = value if value in _STAGES else STAGE_FULL
    _stage_reason = str(state.get("reason", ""))

    try:
        crashed = os.path.exists(_marker_path())
    except Exception:
        crashed = False
    if crashed:
        index = _STAGES.index(_stage)
        _stage = _STAGES[min(index + 1, len(_STAGES) - 1)]
        _stage_reason = "the previous import stopped inside the pose model"
        _write_state(_stage, _stage_reason)
        _clear_marker()
    return _stage


def stage_reason() -> str:
    stage()
    return _stage_reason


def reset_stage() -> None:
    """Forget a demotion and try the full detector again."""
    global _stage, _stage_reason
    _stage, _stage_reason = None, ""
    _clear_marker()
    try:
        os.remove(_state_path())
    except Exception:
        pass
    reset()


def _set_marker(step: str) -> None:
    try:
        with open(_marker_path(), "w", encoding="utf-8") as fh:
            fh.write(step)
    except Exception:
        pass


def _clear_marker() -> None:
    try:
        os.remove(_marker_path())
    except FileNotFoundError:
        pass
    except Exception:
        pass


@contextmanager
def _guarded(step: str):
    """Leave a breadcrumb across a native call so an abort is detectable."""
    _set_marker(step)
    try:
        yield
    finally:
        _clear_marker()


# ------------------------------------------------------------------ detector
_detector = None
_detector_error = False


def _base_options(BaseOptions, path: str):
    """Model asset for the landmarker, as *bytes* where that's supported.

    Handing MediaPipe a path makes its C++ side open the file, and on Windows
    that goes through a narrow (ANSI) API - so a user whose account name isn't
    ASCII has a ``%APPDATA%`` path the library simply cannot read. Python opens
    it correctly, so read the bytes here and pass those instead.
    """
    try:
        with open(path, "rb") as fh:
            return BaseOptions(model_asset_buffer=fh.read())
    except TypeError:
        pass  # older mediapipe: buffers aren't accepted
    except OSError:
        pass  # unreadable here too; let the path form report the problem
    return BaseOptions(model_asset_path=path)


def _get_detector():
    """Create (and cache) the MediaPipe landmarker; ``None`` if unavailable."""
    global _detector, _detector_error
    if _detector is not None or _detector_error:
        return _detector

    level = stage()
    if level == STAGE_OFF:
        _detector_error = True
        return None

    try:
        from mediapipe.tasks.python import BaseOptions, vision

        path = ensure_model()
        if path is None:
            _detector_error = True
            return None
        kwargs = dict(
            base_options=_base_options(BaseOptions, path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
        )
        if level == STAGE_FULL:
            try:
                # Also asks for a per-pixel person mask, which is what lifts a
                # photograph off its background. Older builds don't accept the
                # option, so fall back to landmarks alone rather than failing.
                kwargs["output_segmentation_masks"] = True
                options = vision.PoseLandmarkerOptions(**kwargs)
            except TypeError:
                kwargs.pop("output_segmentation_masks", None)
                options = vision.PoseLandmarkerOptions(**kwargs)
        else:
            options = vision.PoseLandmarkerOptions(**kwargs)

        with _guarded(f"create:{level}"):
            _detector = vision.PoseLandmarker.create_from_options(options)
        return _detector
    except Exception:
        _detector_error = True
        return None


def reset() -> None:
    """Drop the cached detector (used by tests)."""
    global _detector, _detector_error
    try:
        if _detector is not None:
            _detector.close()
    except Exception:
        pass
    _detector = None
    _detector_error = False


def detect_person(image) -> Optional[Person]:
    """Locate a human in ``image`` (a PIL image). ``None`` if not found.

    Never raises: any missing dependency, missing model or detection failure
    returns ``None`` so character import falls back to silhouette analysis.
    """
    detector = _get_detector()
    if detector is None:
        return None

    try:
        import numpy as np
        import mediapipe as mp

        rgb = image.convert("RGB")
        # MediaPipe wraps this buffer rather than copying it, so it has to be
        # contiguous, uint8 and owned by us for the lifetime of the call.
        frame = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        with _guarded(f"detect:{stage()}"):
            result = detector.detect(mp_image)
        if not result.pose_landmarks:
            return None

        landmarks = result.pose_landmarks[0]
        width, height = rgb.size
        person = Person(image_size=(width, height))
        for name, index in LANDMARKS.items():
            if index >= len(landmarks):
                continue
            point = landmarks[index]
            person.points[name] = (point.x * width, point.y * height)
            # Newer builds expose ``visibility``; treat a missing score as
            # "present" rather than discarding an otherwise good landmark.
            person.visibility[name] = float(getattr(point, "visibility", 1.0) or 0.0)
        if not person.points:
            return None
        person.mask = _mask_image(result, rgb.size)
        return person
    except Exception:
        return None


def _mask_image(result, size) -> Optional[object]:
    """Turn the model's segmentation output into a PIL ``L`` mask, or ``None``."""
    masks = getattr(result, "segmentation_masks", None)
    if not masks:
        return None
    try:
        import numpy as np
        from PIL import Image as PILImage

        # ``numpy_view`` is a window onto memory C++ still owns, so copy out of
        # it before anything else - keeping the view alive past the result is a
        # use-after-free, not a Python error.
        data = np.array(masks[0].numpy_view(), dtype="float32", copy=True)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2 or data.size == 0:
            return None
        ramp = np.clip((data - _MASK_LO) / max(1e-6, _MASK_HI - _MASK_LO), 0.0, 1.0)
        pixels = np.ascontiguousarray((ramp * 255.0).astype("uint8"))
        mask = PILImage.fromarray(pixels, mode="L").copy()
        if mask.size != size:
            mask = mask.resize(size, PILImage.BILINEAR)
        return mask
    except Exception:
        return None


def cutout(image, person, min_coverage: float = 0.01):
    """Lift ``person`` off the background of ``image``, returning RGBA.

    A photograph is an opaque rectangle: every crop taken from it carries a
    slab of wall, sky or flag along with the body, and the pet ends up looking
    like a photo with corners rather than like a character. The segmentation
    mask becomes the image's alpha channel, so the bounding box, the row scan
    and every part crop afterwards see only the person.

    Returns ``None`` when there is no usable mask - an empty one, or one that
    covers almost nothing - so the caller keeps the original picture.
    """
    mask = getattr(person, "mask", None)
    if mask is None:
        return None
    try:
        from PIL import Image as PILImage, ImageFilter

        rgba = image.convert("RGBA")
        if mask.size != rgba.size:
            mask = mask.resize(rgba.size, PILImage.BILINEAR)
        # A one-pixel blur softens the mask's staircase without eating hair.
        mask = mask.filter(ImageFilter.GaussianBlur(radius=1.0))
        box = mask.getbbox()
        if box is None:
            return None
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area < rgba.width * rgba.height * min_coverage:
            return None

        # Whichever says "transparent" wins, so an already-cut-out PNG keeps
        # its own edges and only loses anything the model calls background.
        from PIL import ImageChops

        rgba.putalpha(ImageChops.darker(rgba.split()[-1], mask))
        return rgba
    except Exception:
        return None
