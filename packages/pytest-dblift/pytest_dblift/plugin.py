"""pytest11 entry: CLI options and fixture loading."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_dblift.fixtures"]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("dblift", "dblift pytest integration")
    group.addoption(
        "--dblift-url",
        action="store",
        default=None,
        help="Database URL for dblift (e.g. sqlite:////tmp/test.db or postgresql+psycopg://...). "
        "Used when no dblift_config fixture override is provided.",
    )
    group.addoption(
        "--dblift-migrations-dir",
        action="store",
        default="migrations",
        help="Path to the migrations directory. Defaults to migrations.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "dblift: marks tests as using dblift fixtures (provided by pytest-dblift)",
    )
