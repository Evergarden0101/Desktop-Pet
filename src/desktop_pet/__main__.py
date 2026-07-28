"""Enable ``python -m desktop_pet``.

The import tolerates being executed both as a package module (``python -m
desktop_pet``, relative import) and as a bare script (absolute import), so a
frozen build that points here still starts.
"""

from __future__ import annotations

try:
    from .cli import main
except ImportError:  # run as a top-level script (no parent package)
    from desktop_pet.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
