"""Frozen-application entry point (used by PyInstaller).

PyInstaller runs this file as the top-level ``__main__`` script, which means
*relative* imports have no parent package. So, unlike ``desktop_pet/__main__``
(used by ``python -m desktop_pet``), this uses an **absolute** import.

Keeping the freeze entry separate from the package's own ``__main__`` is the
standard fix for the "attempted relative import with no known parent package"
error at exe startup.
"""

import sys


def _run() -> int:
    from desktop_pet.cli import main

    return main()


if __name__ == "__main__":
    sys.exit(_run())
