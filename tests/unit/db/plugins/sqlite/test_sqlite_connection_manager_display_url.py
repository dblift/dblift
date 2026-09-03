"""BUG-08 regression: SQLite banner must show a usable Database URL.

Before this fix, ``SQLiteConnectionManager`` had no ``get_database_url()``
method (SQLite doesn't use JDBC). The command banner calls
``provider.connection_manager.get_database_url()`` via ``hasattr`` and,
finding it absent, falls back to rendering ``Database URL: <not available>``.

The fix adds ``get_database_url()`` that returns a canonical ``sqlite://`` URI
so the banner has something meaningful to print — matching the label
("Database URL", not "legacy URL") that already anticipates non-JDBC providers.
"""

from __future__ import annotations

import os.path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager


def _make_manager(path_attr: dict) -> SQLiteConnectionManager:
    """Build a manager without touching the filesystem.

    ``path_attr`` is applied to the config.database namespace; one of
    ``path`` / ``database`` / ``url`` must be set for ``__init__`` to succeed.
    """
    database = SimpleNamespace(**path_attr)
    config = SimpleNamespace(database=database)
    return SQLiteConnectionManager(config, log=MagicMock())


@pytest.mark.unit
class TestSqliteGetJdbcUrl:
    def test_method_exists(self):
        """hasattr gate in base_command.py:713 must see the method."""
        mgr = _make_manager({"path": "/tmp/x.db"})
        assert hasattr(mgr, "get_database_url")
        assert callable(mgr.get_database_url)

    def test_file_path_becomes_sqlite_uri(self):
        mgr = _make_manager({"path": "/tmp/test.db"})
        assert mgr.get_database_url() == "sqlite:///tmp/test.db"

    def test_memory_db_uri(self):
        mgr = _make_manager({"path": ":memory:"})
        assert mgr.get_database_url() == "sqlite:///:memory:"

    def test_database_attribute_also_works(self):
        """Config can also specify the file under ``database`` instead of ``path``."""
        mgr = _make_manager({"database": "/srv/app.db"})
        assert mgr.get_database_url() == "sqlite:///srv/app.db"

    def test_relative_path_resolved_to_absolute(self):
        """Relative paths get resolved so the URI's authority is always empty.

        Cursor-bot finding: ``sqlite://data/local.db`` parses per RFC 3986
        with ``data`` as authority and ``/local.db`` as path —
        ``base_command.py``'s ``://([^:/]+)`` regex would then mis-extract
        ``data`` as the server name. Resolving to absolute guarantees the
        leading ``/`` after ``sqlite://`` (i.e. ``sqlite:///<abs>``).
        """
        mgr = _make_manager({"path": "data/local.db"})
        url = mgr.get_database_url()
        # URI must start with exactly three slashes so the authority is empty.
        assert url.startswith("sqlite:///"), f"authority must be empty, got: {url!r}"
        # And the path must be the abspath of the input.
        assert url == f"sqlite://{os.path.abspath('data/local.db')}"


@pytest.mark.unit
class TestSqliteProviderDisplayUrl:
    def test_provider_uses_neutral_display_url(self):
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        provider = SQLiteProvider.__new__(SQLiteProvider)
        provider.connection_manager = MagicMock()
        provider.connection_manager.get_database_url.return_value = "sqlite:///tmp/app.db"

        assert provider.get_display_url() == "sqlite:///tmp/app.db"
