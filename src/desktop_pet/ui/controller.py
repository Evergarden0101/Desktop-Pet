"""The application controller: owns the pets, the frame loop and the tray.

This is the top of the UI layer. It builds pets from the active character pack,
drives the fixed-timestep update loop (snapshot desktop -> build environment ->
update each pet -> repaint), and exposes the actions the menus and settings
dialog call into.
"""

from __future__ import annotations

import sys
import time
import traceback
from typing import Dict, List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from ..behaviors import register_default_behaviors
from ..behaviors.autonomy import AutonomyController
from ..config import AppConfig, CharacterPack, discover_characters, resolve_character
from ..core.environment import Environment
from ..core.geometry import Vec2
from ..core.pet import Pet
from ..core.phrases import merged_pool
from ..platform.base import get_backend
from ..rig.loader import LoadedCharacter, load_character
from .imaging import pil_to_qpixmap
from .pet_window import PetOverlay
from .renderer import PetRenderer


class PetApp:
    def __init__(self, config: AppConfig, qapp: QApplication):
        self.config = config
        self.qapp = qapp
        self.character_name = config.character

        backend_pref = None if config.backend == "auto" else config.backend
        self.backend = get_backend(backend_pref)

        self.overlay = PetOverlay()
        self.overlay.context_requested.connect(self._on_context_menu)
        self.overlay.poke_callback = self._on_poke

        self.pets: List[Pet] = []
        self.renderers: Dict[int, PetRenderer] = {}
        self.autonomy: Dict[int, AutonomyController] = {}
        self._next_pet_id = 0

        self._last_time = time.monotonic()
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)

        self.tray = None  # set up in start()

        self._loaded_cache: Dict[str, LoadedCharacter] = {}
        self._last_snapshot = None
        self._tick_error_logged = False

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        bounds = self.backend.snapshot().virtual_bounds()
        self.overlay.set_geometry_from_bounds(bounds)
        self.overlay.show()
        self.overlay.raise_()

        # Exclude our own overlay from Windows window enumeration.
        if hasattr(self.backend, "own_hwnd"):
            try:
                self.backend.own_hwnd = int(self.overlay.winId())
            except Exception:
                pass

        for _ in range(max(1, self.config.pet_count)):
            self.add_pet()

        # The system tray may be unavailable (headless sessions, some Linux
        # desktops); the pet still works without it.
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            from .tray import PetTray

            if QSystemTrayIcon.isSystemTrayAvailable():
                self.tray = PetTray(self)
                self.tray.show()
        except Exception:
            self.tray = None

        interval = max(8, int(1000 / max(1, self.config.fps)))
        self.timer.start(interval)

    def shutdown(self) -> None:
        self.timer.stop()
        if self.tray is not None:
            self.tray.hide()
        self.overlay.close()

    # --------------------------------------------------------------- pets
    def _load_character(self, name: str) -> LoadedCharacter:
        if name in self._loaded_cache:
            return self._loaded_cache[name]
        directory = resolve_character(name) or resolve_character("default")
        pack = CharacterPack.load(directory) if directory else CharacterPack("default", "")
        loaded = load_character(pack)
        self._loaded_cache[name] = loaded
        return loaded

    def add_pet(self) -> Pet:
        loaded = self._load_character(self.character_name)
        pet_id = self._next_pet_id
        self._next_pet_id += 1

        pet = Pet(self.config, skeleton=_clone_skeleton(loaded.skeleton), pet_id=pet_id)
        pet.rescale(self.config.scale)
        pet.phrases = merged_pool(loaded.phrases)
        register_default_behaviors(pet)

        env = Environment(self.backend.snapshot(), self.config.interact_with_windows)
        pet.set_environment(env)
        # Spawn on the primary monitor's floor: the centre of the whole virtual
        # desktop can land on a secondary (or switched-off) monitor.
        primary = env.snapshot.primary()
        if primary is not None:
            work = primary.work_area
            start_x = min(max(work.center.x + pet_id * 60, work.left + 40), work.right - 40)
            floor = work.bottom
        else:
            start_x = env.bounds.center.x + pet_id * 60
            floor = env.world_floor()
        pet.body.position = Vec2(start_x, floor - pet.stand_offset)
        pet.state.change("idle")
        pet.say_category("greet", 2.5)

        renderer = PetRenderer(loaded.render)
        if loaded.parts:
            pixmaps = {
                name: pil_to_qpixmap(part.image)
                for name, part in loaded.parts.items()
                if part.image is not None
            }
            renderer.set_part_pixmaps(pixmaps)

        self.pets.append(pet)
        self.renderers[pet_id] = renderer
        self.autonomy[pet_id] = AutonomyController(pet)
        self.overlay.set_pets(self.pets, self.renderers)
        return pet

    def remove_pet(self, pet: Optional[Pet] = None) -> None:
        if not self.pets:
            return
        target = pet or self.pets[-1]
        self.pets.remove(target)
        self.renderers.pop(target.pet_id, None)
        self.autonomy.pop(target.pet_id, None)
        self.overlay.set_pets(self.pets, self.renderers)
        if not self.pets:
            self.add_pet()  # always keep at least one

    def set_character(self, name: str) -> None:
        self.character_name = name
        self.config.character = name
        self.config.save()
        self._loaded_cache.pop(name, None)
        count = len(self.pets)
        self.pets.clear()
        self.renderers.clear()
        self.autonomy.clear()
        for _ in range(count):
            self.add_pet()

    def set_scale(self, scale: float) -> None:
        self.config.scale = scale
        self.config.save()
        for pet in self.pets:
            pet.rescale(scale)

    # ------------------------------------------------------------- actions
    def trigger(self, pet: Pet, behavior: str, **kwargs) -> None:
        if pet.state.has(behavior):
            pet.state.change(behavior, **kwargs)

    def trigger_all(self, behavior: str, **kwargs) -> None:
        for pet in self.pets:
            self.trigger(pet, behavior, **kwargs)

    def feed(self, pet: Pet) -> None:
        pet.stats.feed(35.0)
        pet.say_category("feed", 2.5)
        self.trigger(pet, "cheer")

    def summon(self) -> None:
        """Teleport every pet above the primary monitor's centre and drop it.

        A recovery action for when pets end up off any visible screen (monitor
        unplugged, resolution/scale changed, window dragged away mid-ride).
        """
        snapshot = self._safe_snapshot()
        if snapshot is None:
            return
        primary = snapshot.primary()
        if primary is None:
            return
        work = primary.work_area
        for i, pet in enumerate(self.pets):
            x = work.center.x + (i - (len(self.pets) - 1) / 2) * 70
            x = min(max(x, work.left + 40), work.right - 40)
            pet.body.position = Vec2(x, work.top + work.height * 0.3)
            pet.body.stop()
            pet.state.change("fall", force=True)
            pet.say_category("summon", 2.5)
        self.overlay.raise_()

    def toggle_follow_cursor(self, enabled: bool) -> None:
        self.config.follow_cursor = enabled
        self.config.save()

    def toggle_gravity(self, enabled: bool) -> None:
        self.config.gravity_enabled = enabled
        for pet in self.pets:
            pet.body.gravity_enabled = enabled
        self.config.save()

    def toggle_window_interaction(self, enabled: bool) -> None:
        self.config.interact_with_windows = enabled
        self.config.save()

    def _on_poke(self, pet: Pet) -> None:
        pet.stats.play(5.0)
        self.trigger(pet, "wave")

    def _on_context_menu(self, pet: Pet, global_pos) -> None:
        from .menu import build_pet_menu

        menu = build_pet_menu(self, pet)
        menu.exec(global_pos)

    def open_settings(self) -> None:
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self)
        dialog.exec()

    def open_characters(self) -> None:
        from .character_dialog import CharacterDialog

        dialog = CharacterDialog(self)
        dialog.exec()
        self._refresh_menus()

    def set_mode(self, mode: str) -> None:
        """Switch the autonomy personality preset (see behaviors.autonomy)."""
        self.config.mode = mode
        # "follow" is the cursor-chasing preset; keep the old flag in sync so
        # both the menu toggle and the mode selector agree.
        self.config.follow_cursor = mode == "follow"
        self.config.save()
        for pet in self.pets:
            pet.say_category("greet", 2.0)
        self._refresh_menus()

    def _refresh_menus(self) -> None:
        if self.tray is not None:
            try:
                self.tray.rebuild_menu()
            except Exception:
                pass

    def quit(self) -> None:
        self.shutdown()
        self.qapp.quit()

    def available_characters(self) -> List[str]:
        return list(discover_characters().keys()) or ["default"]

    # --------------------------------------------------------------- loop
    def _safe_snapshot(self):
        """Take a desktop snapshot, falling back to the last good one.

        A transient Win32 failure (session lock, monitor hot-plug, an
        uncooperative window mid-enumeration) must not blank the app: raising
        out of the timer callback every frame would mean the pet never updates
        or repaints again.
        """
        try:
            snapshot = self.backend.snapshot()
            self._last_snapshot = snapshot
            return snapshot
        except Exception:
            if not self._tick_error_logged:
                traceback.print_exc(file=sys.stderr)
                self._tick_error_logged = True
            return self._last_snapshot

    def _tick(self) -> None:
        now = time.monotonic()
        dt = now - self._last_time
        self._last_time = now
        # Clamp dt so a stalled frame (e.g. laptop wake) doesn't fling the pet.
        dt = min(dt, 1 / 20)

        snapshot = self._safe_snapshot()
        if snapshot is None:
            return  # nothing to work with yet; try again next frame

        # Keep the overlay covering the (possibly changed) virtual desktop.
        bounds = snapshot.virtual_bounds()
        if (
            int(bounds.width) != self.overlay.width()
            or int(bounds.height) != self.overlay.height()
        ):
            self.overlay.set_geometry_from_bounds(bounds)

        for pet in self.pets:
            try:
                env = Environment(snapshot, self.config.interact_with_windows)
                pet.set_environment(env)
                # In follow-cursor mode an idle pet immediately goes to chase.
                if self.config.follow_cursor and pet.state.current_name == "idle":
                    self.trigger(pet, "chase_cursor")
                else:
                    self.autonomy[pet.pet_id].update(dt)
                pet.update(dt)
            except Exception:
                # One misbehaving pet/behaviour must not take the app down.
                if not self._tick_error_logged:
                    traceback.print_exc(file=sys.stderr)
                    self._tick_error_logged = True

        self.overlay.refresh()


def _clone_skeleton(skeleton):
    """Deep-ish copy so each pet animates independently."""
    from ..core.skeleton import Bone, Skeleton

    bones = []
    for name in skeleton.order:
        b = skeleton.bones[name]
        bones.append(
            Bone(
                name=b.name,
                length=b.length,
                parent=b.parent,
                rest_angle=b.rest_angle,
                local_angle=b.rest_angle,
                part=b.part,
                z_order=b.z_order,
                pivot=Vec2(b.pivot.x, b.pivot.y),
            )
        )
    return Skeleton(bones)
