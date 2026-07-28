"""Headless tests for the app bootstrap helpers (no PySide6 needed)."""

from __future__ import annotations

import os

from desktop_pet.app import _configure_high_dpi


def test_high_dpi_scaling_disabled(monkeypatch):
    """Qt must run in physical pixels so it aligns with Win32 coordinates."""
    monkeypatch.delenv("QT_ENABLE_HIGHDPI_SCALING", raising=False)
    monkeypatch.delenv("DESKTOP_PET_QT_SCALING", raising=False)
    _configure_high_dpi()
    assert os.environ["QT_ENABLE_HIGHDPI_SCALING"] == "0"


def test_high_dpi_escape_hatch(monkeypatch):
    """DESKTOP_PET_QT_SCALING=1 leaves Qt's own scaling untouched."""
    monkeypatch.setenv("DESKTOP_PET_QT_SCALING", "1")
    monkeypatch.delenv("QT_ENABLE_HIGHDPI_SCALING", raising=False)
    _configure_high_dpi()
    assert "QT_ENABLE_HIGHDPI_SCALING" not in os.environ
