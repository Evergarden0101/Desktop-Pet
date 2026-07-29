"""Desktop Pet - a highly interactive, customizable desktop companion.

The package is layered so the simulation core has no GUI dependencies:

* :mod:`desktop_pet.core`      - geometry, skeleton, physics, environment, pet
* :mod:`desktop_pet.rig`       - body-part extraction and pose generation
* :mod:`desktop_pet.behaviors` - the pet's state machine of actions
* :mod:`desktop_pet.platform`  - OS backends (Windows / synthetic)
* :mod:`desktop_pet.ui`        - the PySide6 overlay window (imported lazily)
"""

from __future__ import annotations

__version__ = "1.5.1"
__all__ = ["__version__"]
