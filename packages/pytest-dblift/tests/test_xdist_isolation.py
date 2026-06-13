"""xdist worker isolation test for pytest-dblift (Task 4.3).

Verifies default (no --dblift-url) produces worker-specific SQLite file paths
using _worker_id so `pytest -n 2 --dist=loadscope` works without DB collisions
on the session-scoped dblift_config / engine / client fixtures.

Run exactly:
    cd packages/pytest-dblift && PYTHONPATH=../.. python -m pytest tests/test_xdist_isolation.py -n 2 --dist=loadscope -q

This test is the TDD "RED" before the logic change in _client (and plugin touch).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from pytest_dblift._client import _worker_id


def test_xdist_worker_isolation(
    pytestconfig: pytest.Config,
    dblift_config: dict[str, Any],
    dblift_migrated_db: Any,
    dblift_engine: Any,
) -> None:
    """Prove per-worker DB files: under xdist gw workers, url contains workerid and
    data writes (using smoke table) are isolated to each worker's DB (count==1 for tagged row).
    """
    wid = _worker_id(pytestconfig)
    url = dblift_config["url"]

    # Under -n2, tests execute in worker processes (gw0, gw1, ...); default url must be worker-specific.
    # (Currently, pre-worker logic, this assert will fail for gw* because url always ends in test.db)
    if wid != "master":
        assert wid in url, (
            f"worker isolation missing: worker {wid!r} not found in default url {url!r} "
            "(shared DB file would cause collisions/races for session fixtures)"
        )

    # Exercise the fixtures under the (now or soon) isolated DB for this worker.
    assert isinstance(dblift_config, dict)
    assert "sqlite" in url and ":memory:" not in url
    assert "migrations_dir" in dblift_config

    # Use dblift_migrated_db (which triggers migrate on this worker's client) + engine
    # to write a worker-specific row and assert only it is visible here.
    tag = f"iso-{wid}"
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO pytest_dblift_smoke (name) VALUES (:n)"), {"n": tag})
        conn.commit()
        cnt = conn.execute(
            text("SELECT COUNT(*) FROM pytest_dblift_smoke WHERE name = :n"), {"n": tag}
        ).scalar()
        assert cnt == 1, f"expected exactly 1 row for this worker's tag on its DB, got {cnt}"

    # The migrated_db fixture succeeded for this worker.
    assert dblift_migrated_db is not None
