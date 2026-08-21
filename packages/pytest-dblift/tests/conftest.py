"""Self-test configuration: point migrations_dir at tests/migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pytest_dblift._client import resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    cfg = dict(resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory))
    cfg["migrations_dir"] = str((Path(__file__).parent / "migrations").resolve())
    return cfg
