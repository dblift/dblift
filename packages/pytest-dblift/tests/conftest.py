"""Self-test configuration for pytest-dblift package tests.

Overrides dblift_config so that the default migrations_dir points at the
local tests/migrations (contains the V1__init.sql smoke script).
Respects --dblift-url if passed on the pytest CLI for these tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pytest_dblift._client import resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Override to force migrations_dir to the package-local test migrations."""
    cfg = resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory)
    cfg = dict(cfg)  # copy
    local_migrations = (Path(__file__).parent / "migrations").resolve()
    cfg["migrations_dir"] = str(local_migrations)
    return cfg
