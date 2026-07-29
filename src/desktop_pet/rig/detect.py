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


@dataclass
class Person:
    """Detected body landmarks, in *pixel* coordinates of the source image."""

    points: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    visibility: Dict[str, float] = field(default_factory=dict)
    image_size: Tuple[int, int] = (0, 0)

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
    try:
        import mediapipe  # noqa: F401
    except Exception:
        return False
    return ensure_model(download=download) is not None


# ------------------------------------------------------------------ detector
_detector = None
_detector_error = False


def _get_detector():
    """Create (and cache) the MediaPipe landmarker; ``None`` if unavailable."""
    global _detector, _detector_error
    if _detector is not None or _detector_error:
        return _detector

    try:
        from mediapipe.tasks.python import BaseOptions, vision

        path = ensure_model()
        if path is None:
            _detector_error = True
            return None
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
        )
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
        frame = np.asarray(rgb)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
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
        return person if person.points else None
    except Exception:
        return None
