"""SQLite tests for pytest-dblift helpers and fixtures."""

from __future__ import annotations

from typing import Any

import pytest


def test_resolve_dblift_config_reads_cli_url(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from pytest_dblift._client import resolve_dblift_config

    class DummyConfig:
        rootdir = "/tmp"

        def getoption(self, name: str, default: Any = None) -> Any:
            if name == "--dblift-url":
                return "sqlite:////tmp/dblift_custom_test.db"
            if name == "--dblift-migrations-dir":
                return "migrations"
            return default

    cfg = resolve_dblift_config(DummyConfig(), tmp_path_factory=tmp_path_factory)
    assert "dblift_custom_test.db" in cfg["url"]
    assert "migrations" in cfg["migrations_dir"]


def test_worker_id_master_without_xdist(pytestconfig: pytest.Config) -> None:
    from pytest_dblift._client import _worker_id

    if getattr(pytestconfig, "workerinput", None):
        pytest.skip("this assertion is for a non-xdist controller process")
    assert _worker_id(pytestconfig) == "master"
