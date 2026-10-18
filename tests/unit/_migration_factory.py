"""Build ``Migration`` objects for tests, with the checksum the script manager would give."""

from typing import Any

from dblift.core.logger import NullLog
from dblift.core.migration.encoding import read_migration_text
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

_SCRIPT_MANAGER = MigrationScriptManager(NullLog())


def make_migration(*args: Any, **kwargs: Any) -> Migration:
    """Return ``Migration(*args, **kwargs)``, defaulting ``checksum`` to the script manager's.

    The checksum is taken from the file when a script path is given and from ``content``
    otherwise. An explicit ``checksum=`` (including ``None``) is passed through untouched.
    """
    if "checksum" not in kwargs:
        path = args[0] if args else kwargs.get("script", kwargs.get("script_path"))
        if path is not None:
            text = read_migration_text(
                path,
                configured_encoding=kwargs.get("script_encoding", "utf-8"),
                detect_encoding=kwargs.get("detect_encoding", False),
            )
        else:
            text = kwargs.get("content") or ""
        kwargs["checksum"] = _SCRIPT_MANAGER.calculate_checksum(text)
    return Migration(*args, **kwargs)
