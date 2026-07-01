"""Parity: _find_undo_versions marks Python undoable via a U*.py companion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from core.migration.ui.data_collector import MigrationDataCollector


def _make_collector() -> MigrationDataCollector:
    script_manager = MagicMock()
    script_manager.extract_version.side_effect = lambda name: name.split("__")[0].lstrip("VU")
    collector = MigrationDataCollector.__new__(MigrationDataCollector)
    collector.script_manager = script_manager
    return collector


def test_python_undoable_via_undo_script(tmp_path: Path):
    (tmp_path / "V1__create.py").write_text("def migrate(context):\n    pass\n")
    (tmp_path / "U1__drop.py").write_text("def migrate(context):\n    pass\n")
    versions = _make_collector()._find_undo_versions(tmp_path)
    assert "1" in versions


def test_inline_undo_in_versioned_py_not_undoable(tmp_path: Path):
    (tmp_path / "V1__create.py").write_text(
        "def migrate(context):\n    pass\n\ndef undo(context):\n    pass\n"
    )
    versions = _make_collector()._find_undo_versions(tmp_path)
    assert "1" not in versions


def test_sql_undoable_via_undo_script(tmp_path: Path):
    (tmp_path / "U2__drop.sql").write_text("DROP TABLE t;")
    versions = _make_collector()._find_undo_versions(tmp_path)
    assert "2" in versions
