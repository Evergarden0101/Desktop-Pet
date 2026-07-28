"""A minimal synchronous publish/subscribe event bus.

Used to decouple the UI layer (mouse clicks, tray actions) from the simulation
layer (the pet's behaviours), and to let systems such as stats broadcast
notifications without importing each other.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, DefaultDict, List

Listener = Callable[..., None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: DefaultDict[str, List[Listener]] = defaultdict(list)

    def subscribe(self, event: str, listener: Listener) -> Callable[[], None]:
        self._listeners[event].append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners[event]:
                self._listeners[event].remove(listener)

        return _unsubscribe

    def emit(self, event: str, **data) -> None:
        # Iterate over a copy so listeners may unsubscribe while handling.
        for listener in list(self._listeners.get(event, ())):
            listener(**data)

    def clear(self) -> None:
        self._listeners.clear()
