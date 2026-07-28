"""A settings dialog exposing the most useful :class:`AppConfig` options.

Anything not surfaced here can still be edited in ``config.json``; this covers
the day-to-day knobs (size, speeds, which behaviours are allowed, window
interaction, autonomy pacing, start-on-login).
"""

from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..behaviors import DEFAULT_BEHAVIORS
from ..behaviors.autonomy import MODE_LABELS
from ..rig.body_parts import BODY_STYLES
from ..platform.autostart import set_start_on_login

if TYPE_CHECKING:  # pragma: no cover
    from .controller import PetApp

# Behaviours the user may toggle on/off for the autonomy brain.
_TOGGLEABLE = [b for b in DEFAULT_BEHAVIORS if b.autonomous]


class SettingsDialog(QDialog):
    def __init__(self, app: "PetApp"):
        super().__init__()
        self.app = app
        self.config = app.config
        self.setWindowTitle("Desktop Pet - Settings")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(self._appearance_group())
        layout.addWidget(self._movement_group())
        layout.addWidget(self._interaction_group())
        layout.addWidget(self._behaviors_group())

        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Close
        )
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(buttons)

    # -------------------------------------------------------------- groups
    def _appearance_group(self) -> QWidget:
        box = QGroupBox("Appearance")
        form = QFormLayout(box)

        self.style_combo = QComboBox()
        for style_name, style_def in BODY_STYLES.items():
            self.style_combo.addItem(style_def["label"], style_name)
        idx = self.style_combo.findData(self.config.body_style)
        self.style_combo.setCurrentIndex(max(0, idx))
        self.style_combo.setToolTip(
            "Body proportions for characters drawn from shapes. Imported "
            "picture characters keep their own proportions."
        )
        form.addRow("Look", self.style_combo)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.3, 4.0)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(self.config.scale)
        form.addRow("Size", self.scale_spin)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.2, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(self.config.opacity)
        form.addRow("Opacity", self.opacity_spin)

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(15, 144)
        self.fps_spin.setValue(self.config.fps)
        form.addRow("Frame rate", self.fps_spin)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 20)
        self.count_spin.setValue(len(self.app.pets))
        form.addRow("Number of pets", self.count_spin)
        return box

    def _movement_group(self) -> QWidget:
        box = QGroupBox("Movement")
        form = QFormLayout(box)

        self.walk_spin = self._speed_spin(self.config.walk_speed)
        form.addRow("Walk speed", self.walk_spin)
        self.run_spin = self._speed_spin(self.config.run_speed)
        form.addRow("Run speed", self.run_spin)
        self.climb_spin = self._speed_spin(self.config.climb_speed)
        form.addRow("Climb speed", self.climb_spin)
        self.creep_spin = self._speed_spin(self.config.creep_speed)
        form.addRow("Creep speed", self.creep_spin)

        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        self.autonomy_min = QDoubleSpinBox()
        self.autonomy_min.setRange(0.5, 60)
        self.autonomy_min.setValue(self.config.autonomy_min)
        self.autonomy_max = QDoubleSpinBox()
        self.autonomy_max.setRange(1.0, 120)
        self.autonomy_max.setValue(self.config.autonomy_max)
        hbox.addWidget(QLabel("min"))
        hbox.addWidget(self.autonomy_min)
        hbox.addWidget(QLabel("max"))
        hbox.addWidget(self.autonomy_max)
        form.addRow("Idle before acting (s)", row)
        return box

    def _interaction_group(self) -> QWidget:
        box = QGroupBox("Interaction")
        form = QFormLayout(box)

        self.mode_combo = QComboBox()
        for mode_name, mode_label in MODE_LABELS.items():
            self.mode_combo.addItem(mode_label, mode_name)
        index = self.mode_combo.findData(self.config.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        form.addRow("Mode", self.mode_combo)

        self.windows_check = QCheckBox("Walk on and climb application windows")
        self.windows_check.setChecked(self.config.interact_with_windows)
        form.addRow(self.windows_check)

        self.climb_chance_spin = QDoubleSpinBox()
        self.climb_chance_spin.setRange(0.0, 1.0)
        self.climb_chance_spin.setSingleStep(0.05)
        self.climb_chance_spin.setValue(self.config.climb_chance)
        self.climb_chance_spin.setToolTip(
            "How eagerly the pet climbs a window edge it bumps into (0-1)."
        )
        form.addRow("Climb eagerness", self.climb_chance_spin)

        self.gravity_check = QCheckBox("Gravity (pet falls and can be thrown)")
        self.gravity_check.setChecked(self.config.gravity_enabled)
        form.addRow(self.gravity_check)

        self.speech_check = QCheckBox("Show speech bubbles")
        self.speech_check.setChecked(self.config.show_speech_bubbles)
        form.addRow(self.speech_check)

        self.stats_check = QCheckBox("Enable hunger/energy stats")
        self.stats_check.setChecked(self.config.stats_enabled)
        form.addRow(self.stats_check)

        self.autostart_check = QCheckBox("Start automatically at login")
        self.autostart_check.setChecked(self.config.start_on_login)
        form.addRow(self.autostart_check)

        characters = QPushButton("Manage characters / add from a picture...")
        characters.clicked.connect(self._open_characters)
        form.addRow(characters)
        return box

    def _open_characters(self) -> None:
        self.app.open_characters()

    def _behaviors_group(self) -> QWidget:
        box = QGroupBox("Allowed autonomous actions")
        vbox = QVBoxLayout(box)
        self.behavior_checks: Dict[str, QCheckBox] = {}
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        for i, behavior in enumerate(_TOGGLEABLE):
            check = QCheckBox(behavior.label)
            check.setChecked(behavior.name in self.config.enabled_behaviors)
            self.behavior_checks[behavior.name] = check
            hbox.addWidget(check)
            if (i + 1) % 3 == 0:
                vbox.addWidget(row)
                row = QWidget()
                hbox = QHBoxLayout(row)
                hbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(row)
        return box

    def _speed_spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(5, 1000)
        spin.setSingleStep(5)
        spin.setValue(value)
        return spin

    # --------------------------------------------------------------- apply
    def _apply(self) -> None:
        cfg = self.config
        cfg.scale = self.scale_spin.value()
        cfg.opacity = self.opacity_spin.value()
        cfg.fps = self.fps_spin.value()
        cfg.walk_speed = self.walk_spin.value()
        cfg.run_speed = self.run_spin.value()
        cfg.climb_speed = self.climb_spin.value()
        cfg.creep_speed = self.creep_spin.value()
        cfg.autonomy_min = self.autonomy_min.value()
        cfg.autonomy_max = max(self.autonomy_max.value(), self.autonomy_min.value())
        new_style = self.style_combo.currentData() or "cute"
        style_changed = new_style != cfg.body_style
        cfg.mode = self.mode_combo.currentData() or "free"
        cfg.follow_cursor = cfg.mode == "follow"
        cfg.climb_chance = self.climb_chance_spin.value()
        cfg.interact_with_windows = self.windows_check.isChecked()
        cfg.gravity_enabled = self.gravity_check.isChecked()
        cfg.show_speech_bubbles = self.speech_check.isChecked()
        cfg.stats_enabled = self.stats_check.isChecked()
        cfg.start_on_login = self.autostart_check.isChecked()
        cfg.enabled_behaviors = [
            name for name, chk in self.behavior_checks.items() if chk.isChecked()
        ]
        cfg.save()

        # Apply live where it matters.
        self.app.set_scale(cfg.scale)
        self.app.overlay.setWindowOpacity(cfg.opacity)
        self.app.timer.setInterval(max(8, int(1000 / max(1, cfg.fps))))
        for pet in self.app.pets:
            pet.body.gravity_enabled = cfg.gravity_enabled
        if style_changed:
            self.app.set_body_style(new_style)
        self._match_pet_count(self.count_spin.value())
        set_start_on_login(cfg.start_on_login)

    def _match_pet_count(self, target: int) -> None:
        while len(self.app.pets) < target:
            self.app.add_pet()
        while len(self.app.pets) > target:
            self.app.remove_pet(self.app.pets[-1])
