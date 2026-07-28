"""Right-click / tray menu construction.

Kept separate from the controller so both the per-pet context menu and the
system-tray menu can share exactly the same action set.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

from ..behaviors.autonomy import MODE_LABELS
from ..rig.body_parts import BODY_STYLES

if TYPE_CHECKING:  # pragma: no cover
    from ..core.pet import Pet
    from .controller import PetApp

# (behaviour name, menu label) pairs offered as manual "Do..." actions.
_ACTION_ITEMS = [
    ("wave", "Wave"),
    ("cheer", "Cheer"),
    ("sit", "Sit down"),
    ("sleep", "Sleep"),
    ("creep", "Creep"),
    ("walk", "Walk around"),
    ("run", "Run around"),
    ("climb", "Climb nearest edge"),
]

_SIZE_ITEMS = [("Small", 0.7), ("Medium", 1.0), ("Large", 1.4), ("Huge", 2.0)]


def build_pet_menu(app: "PetApp", pet: Optional["Pet"] = None) -> QMenu:
    menu = QMenu()

    title = "Desktop Pet" if pet is None else f"{app.character_name}"
    header = menu.addAction(title)
    header.setEnabled(False)
    menu.addSeparator()

    # --- Do... actions --------------------------------------------------- #
    do_menu = menu.addMenu("Do")
    for name, label in _ACTION_ITEMS:
        act = do_menu.addAction(label)
        act.triggered.connect(_bind_behavior(app, pet, name))

    if pet is not None:
        feed = menu.addAction("Feed")
        feed.triggered.connect(lambda: app.feed(pet))

    # --- Mode ------------------------------------------------------------ #
    mode_menu = menu.addMenu("Mode")
    mode_group = QActionGroup(mode_menu)
    mode_group.setExclusive(True)
    for mode_name, mode_label in MODE_LABELS.items():
        act = mode_menu.addAction(mode_label)
        act.setCheckable(True)
        act.setChecked(app.config.mode == mode_name)
        mode_group.addAction(act)
        act.triggered.connect(_bind_mode(app, mode_name))

    # --- Toggles --------------------------------------------------------- #
    gravity = menu.addAction("Gravity")
    gravity.setCheckable(True)
    gravity.setChecked(app.config.gravity_enabled)
    gravity.toggled.connect(app.toggle_gravity)

    windows = menu.addAction("Play on app windows")
    windows.setCheckable(True)
    windows.setChecked(app.config.interact_with_windows)
    windows.toggled.connect(app.toggle_window_interaction)

    # --- Look ------------------------------------------------------------ #
    style_menu = menu.addMenu("Look")
    style_group = QActionGroup(style_menu)
    style_group.setExclusive(True)
    for style_name, style_def in BODY_STYLES.items():
        act = style_menu.addAction(style_def["label"])
        act.setCheckable(True)
        act.setChecked(app.config.body_style == style_name)
        style_group.addAction(act)
        act.triggered.connect(_bind_style(app, style_name))

    # --- Size ------------------------------------------------------------ #
    size_menu = menu.addMenu("Size")
    size_group = QActionGroup(size_menu)
    size_group.setExclusive(True)
    for label, scale in _SIZE_ITEMS:
        act = size_menu.addAction(label)
        act.setCheckable(True)
        act.setChecked(abs(app.config.scale - scale) < 0.01)
        size_group.addAction(act)
        act.triggered.connect(_bind_scale(app, scale))

    # --- Character ------------------------------------------------------- #
    char_menu = menu.addMenu("Character")
    chars = app.available_characters()
    char_group = QActionGroup(char_menu)
    char_group.setExclusive(True)
    for name in chars:
        act = char_menu.addAction(name)
        act.setCheckable(True)
        act.setChecked(name == app.character_name)
        char_group.addAction(act)
        act.triggered.connect(_bind_character(app, name))
    char_menu.addSeparator()
    manage = char_menu.addAction("Manage characters...")
    manage.triggered.connect(lambda _checked=False: app.open_characters())
    add_char = char_menu.addAction("Add from a picture...")
    add_char.triggered.connect(lambda _checked=False: app.open_characters())

    menu.addSeparator()

    summon = menu.addAction("Summon pets")
    summon.setToolTip("Bring every pet to the middle of the main screen")
    summon.triggered.connect(lambda _checked=False: app.summon())

    add = menu.addAction("Add another pet")
    add.triggered.connect(lambda: app.add_pet())
    if pet is not None:
        remove = menu.addAction("Remove this pet")
        remove.triggered.connect(lambda: app.remove_pet(pet))

    menu.addSeparator()
    settings = menu.addAction("Settings...")
    settings.triggered.connect(app.open_settings)

    quit_act = menu.addAction("Quit")
    quit_act.triggered.connect(app.quit)
    return menu


# QAction.triggered passes a bool; wrap so we ignore it and bind arguments.
def _bind_behavior(app, pet, name):
    def handler(_checked=False):
        if pet is not None:
            app.trigger(pet, name)
        else:
            app.trigger_all(name)

    return handler


def _bind_scale(app, scale):
    def handler(_checked=False):
        app.set_scale(scale)

    return handler


def _bind_character(app, name):
    def handler(_checked=False):
        app.set_character(name)

    return handler


def _bind_style(app, style):
    def handler(_checked=False):
        app.set_body_style(style)

    return handler


def _bind_mode(app, mode):
    def handler(_checked=False):
        app.set_mode(mode)

    return handler
