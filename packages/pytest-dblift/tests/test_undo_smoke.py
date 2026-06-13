"""Smoke test exercising dblift_undo_smoke fixture with a Python migration declaring undo (Task 4.4).

TDD: written first to produce RED (unknown fixture), then fixture added for GREEN.
Uses inline temp migrations dir + override so no changes outside this file + fixtures.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text


@pytest.fixture(scope="session")
def dblift_config(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Session override for undo-smoke tests only: use temp dir with a Python migration that has both migrate() and undo()."""
    from pytest_dblift._client import resolve_dblift_config

    cfg = resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory)
    cfg = dict(cfg)  # copy

    mig_dir = tmp_path_factory.mktemp("migrations_undo_smoke")
    py_script = mig_dir / "V1__table_with_undo.py"
    py_script.write_text(
        "def migrate(context):\n"
        '    context.execute("CREATE TABLE undo_smoke_table (id INTEGER PRIMARY KEY, name TEXT)")\n'
        "\n"
        "def undo(context):\n"
        '    context.execute("DROP TABLE undo_smoke_table")\n'
    )
    cfg["migrations_dir"] = str(mig_dir)
    return cfg


def test_dblift_undo_smoke_applies_forward_and_allows_undo(
    dblift_undo_smoke: Any, dblift_engine: Any
) -> None:
    """dblift_undo_smoke ensures forward migration (the Python one with undo), yields client.

    Test drives undo() and asserts state change (table created by migrate, dropped by undo).
    This exercises the real undo path for Python migrations through the pytest fixtures + DBLiftClient.
    """
    from api import DBLiftClient

    assert isinstance(dblift_undo_smoke, DBLiftClient)

    # Forward migration has run: table created by the migrate(context) in the .py
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO undo_smoke_table (name) VALUES ('before-undo')"))
        conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM undo_smoke_table")).scalar()
        assert count == 1

    # Exercise the undo path (the point of this smoke fixture)
    undo_result = dblift_undo_smoke.undo(target_version="0")
    assert getattr(undo_result, "success", False), (
        f"undo failed: {getattr(undo_result, 'error_message', undo_result)}"
    )

    # Post-undo: table must be gone (reverted by undo(context))
    with dblift_engine.connect() as conn:
        try:
            conn.execute(text("SELECT COUNT(*) FROM undo_smoke_table"))
            table_exists = True
        except Exception:
            table_exists = False
        assert not table_exists, "undo should have dropped undo_smoke_table via the Python undo fn"
