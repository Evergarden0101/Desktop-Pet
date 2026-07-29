"""Surviving a crash inside the native pose detector.

MediaPipe is a C++ library: when it is unhappy it calls ``abort()`` rather than
raising, so no ``try``/``except`` in the package can catch it and the whole app
goes down with it. The only defence is to notice that the last attempt never
came back and ask for less next time - which is what these tests pin down.
"""

from __future__ import annotations

import os

import pytest

from desktop_pet.rig import detect


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Point the detector's state files at a temp dir and reset the cache."""
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(detect, "model_dir", lambda: str(models))
    monkeypatch.delenv(detect._ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(detect, "_stage", None)
    monkeypatch.setattr(detect, "_stage_reason", "")
    yield models
    detect._stage = None
    detect._stage_reason = ""


def _forget():
    """Drop the per-process cache so the next stage() re-reads from disk."""
    detect._stage = None
    detect._stage_reason = ""


# ------------------------------------------------------------------- staging
def test_starts_at_full_quality():
    assert detect.stage() == detect.STAGE_FULL
    assert detect.stage_reason() == ""


def test_a_crashed_attempt_demotes_one_level(isolated_state):
    # A marker left behind means the process died inside the native call.
    (isolated_state / "detector.running").write_text("detect:full")
    assert detect.stage() == detect.STAGE_LANDMARKS
    assert "stopped inside" in detect.stage_reason()
    # The marker is consumed, so the demotion happens once, not every launch.
    assert not (isolated_state / "detector.running").exists()

    _forget()
    assert detect.stage() == detect.STAGE_LANDMARKS


def test_crashing_again_switches_the_detector_off(isolated_state):
    (isolated_state / "detector.running").write_text("detect:full")
    assert detect.stage() == detect.STAGE_LANDMARKS

    _forget()
    (isolated_state / "detector.running").write_text("detect:landmarks")
    assert detect.stage() == detect.STAGE_OFF

    # ...and never below that.
    _forget()
    (isolated_state / "detector.running").write_text("detect:off")
    assert detect.stage() == detect.STAGE_OFF
    assert not detect.available(download=False)


def test_a_clean_run_leaves_no_marker(isolated_state):
    with detect._guarded("detect:full"):
        assert (isolated_state / "detector.running").exists()
    assert not (isolated_state / "detector.running").exists()

    _forget()
    assert detect.stage() == detect.STAGE_FULL


def test_the_marker_is_cleared_even_when_the_call_raises(isolated_state):
    with pytest.raises(RuntimeError):
        with detect._guarded("detect:full"):
            raise RuntimeError("a Python-level failure is not a crash")
    assert not (isolated_state / "detector.running").exists()

    _forget()
    assert detect.stage() == detect.STAGE_FULL


def test_reset_restores_full_quality(isolated_state):
    (isolated_state / "detector.running").write_text("detect:full")
    assert detect.stage() == detect.STAGE_LANDMARKS

    detect.reset_stage()
    assert detect.stage() == detect.STAGE_FULL
    assert detect.stage_reason() == ""


def test_environment_override_wins(monkeypatch, isolated_state):
    (isolated_state / "detector.running").write_text("detect:full")
    monkeypatch.setenv(detect._ENV_OVERRIDE, "off")
    _forget()
    assert detect.stage() == detect.STAGE_OFF
    assert not detect.available(download=False)


def test_unreadable_state_does_not_break_anything(isolated_state):
    (isolated_state / "detector.json").write_text("{ not json at all")
    assert detect.stage() == detect.STAGE_FULL


def test_detector_is_not_created_when_switched_off(monkeypatch):
    monkeypatch.setenv(detect._ENV_OVERRIDE, "off")
    _forget()
    detect.reset()
    assert detect._get_detector() is None
    img = pytest.importorskip("PIL.Image").new("RGBA", (64, 64), (255, 0, 0, 255))
    assert detect.detect_person(img) is None
    detect.reset()


# ---------------------------------------------------------------- model load
def test_model_is_handed_over_as_bytes(tmp_path):
    """A path goes through MediaPipe's narrow file API and breaks on non-ASCII
    Windows profiles; bytes read by Python don't."""

    class FakeBaseOptions:
        def __init__(self, model_asset_path=None, model_asset_buffer=None):
            self.path = model_asset_path
            self.buffer = model_asset_buffer

    model = tmp_path / "模型.task"  # deliberately not ASCII
    model.write_bytes(b"weights")
    options = detect._base_options(FakeBaseOptions, str(model))
    assert options.buffer == b"weights"
    assert options.path is None


def test_model_falls_back_to_a_path_on_older_mediapipe(tmp_path):
    class OldBaseOptions:
        def __init__(self, model_asset_path=None):
            self.path = model_asset_path

    model = tmp_path / "m.task"
    model.write_bytes(b"weights")
    assert detect._base_options(OldBaseOptions, str(model)).path == str(model)


# ------------------------------------------------------------------ log file
def test_output_capture_only_applies_to_a_frozen_gui(monkeypatch, tmp_path):
    pytest.importorskip("PySide6")
    import sys

    from desktop_pet.ui import errors

    monkeypatch.setattr("desktop_pet.config.config_dir", lambda: str(tmp_path))
    # Running from source: streams are real, so nothing is redirected.
    assert errors.capture_output() is None

    # Pretend to be a windowed frozen build, which has no streams at all.
    # capture_output redirects the real descriptors, so keep copies to put back.
    saved = {fd: os.dup(fd) for fd in (1, 2)}
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.stderr", None)
    try:
        path = errors.capture_output()
        assert path and os.path.exists(path)
        print("native-looking output")  # goes to the log, not the terminal
        with open(path, encoding="utf-8") as fh:
            assert "native-looking output" in fh.read()
    finally:
        for fd, copy in saved.items():
            os.dup2(copy, fd)
            os.close(copy)
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
