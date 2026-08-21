"""dblift_undo uses companion U* scripts, not an undo() function inside V*.py."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from api import DBLiftClient


def test_dblift_undo_reverts_via_companion_script(
    dblift_migrated_db: DBLiftClient,
    dblift_undo: Any,
    dblift_engine: Any,
) -> None:
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO pytest_dblift_smoke (name) VALUES ('before-undo')"))
        conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke")).scalar()
        assert count == 1

    result = dblift_undo(target_version="0")
    assert result.success is True

    with dblift_engine.connect() as conn:
        try:
            conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke"))
            exists = True
        except Exception:
            exists = False
    assert not exists


def test_dblift_undo_is_callable(dblift_undo: Any) -> None:
    assert callable(dblift_undo)
