"""Default SQLite URLs are per xdist worker."""

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
    wid = _worker_id(pytestconfig)
    url = dblift_config["url"]

    if wid != "master":
        assert wid in url, (
            f"worker isolation missing: worker {wid!r} not in default url {url!r}"
        )

    assert "sqlite" in url and ":memory:" not in url
    tag = f"iso-{wid}"
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO pytest_dblift_smoke (name) VALUES (:n)"), {"n": tag})
        conn.commit()
        cnt = conn.execute(
            text("SELECT COUNT(*) FROM pytest_dblift_smoke WHERE name = :n"), {"n": tag}
        ).scalar()
        assert cnt == 1
