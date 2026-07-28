"""Right-click / tray menu construction.

Kept separate from the controller so both the per-pet context menu and the
system-tray menu can share exactly the same action set.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

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

    # --- Toggles --------------------------------------------------------- #
    follow = menu.addAction("Follow cursor")
    follow.setCheckable(True)
    follow.setChecked(app.config.follow_cursor)
    follow.toggled.connect(app.toggle_follow_cursor)

    gravity = menu.addAction("Gravity")
    gravity.setCheckable(True)
    gravity.setChecked(app.config.gravity_enabled)
    gravity.toggled.connect(app.toggle_gravity)

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
    chars = app.available_characters()
    if len(chars) > 1:
        char_menu = menu.addMenu("Character")
        char_group = QActionGroup(char_menu)
        char_group.setExclusive(True)
        for name in chars:
            act = char_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == app.character_name)
            char_group.addAction(act)
            act.triggered.connect(_bind_character(app, name))

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
