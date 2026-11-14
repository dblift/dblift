"""Existence checks that raise when a path cannot be examined, instead of saying "absent".

``Path.exists()`` swallows every ``OSError`` from Python 3.14 (3.11 to 3.13 raise some), and
``os.path.exists()`` always does; an unreadable path would be reported as missing.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Optional, Union


def _stat_or_none(path: Union[str, Path]) -> Optional[os.stat_result]:
    try:
        return os.stat(path)
    except (FileNotFoundError, NotADirectoryError, ValueError):  # ValueError: embedded NUL
        return None


def path_exists(path: Union[str, Path]) -> bool:
    """Return whether *path* exists; raise ``OSError`` if it cannot be examined."""
    return _stat_or_none(path) is not None


def path_is_file(path: Union[str, Path]) -> bool:
    """Return whether *path* is a regular file; raise ``OSError`` if it cannot be examined."""
    found = _stat_or_none(path)
    return found is not None and stat.S_ISREG(found.st_mode)


def path_is_dir(path: Union[str, Path]) -> bool:
    """Return whether *path* is a directory; raise ``OSError`` if it cannot be examined."""
    found = _stat_or_none(path)
    return found is not None and stat.S_ISDIR(found.st_mode)
