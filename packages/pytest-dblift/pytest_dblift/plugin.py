"""pytest-dblift pytest11 plugin entry point.

Registers CLI options and loads the fixtures module.

Usage:
    pytest --help | grep -A 20 dblift
    pytest --markers | grep dblift
Supports xdist worker isolation for default SQLite (via _client._worker_id).
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add dblift-specific CLI options."""
    group = parser.getgroup("dblift", "dblift pytest integration")
    group.addoption(
        "--dblift-url",
        action="store",
        default=None,
        help="Database URL for dblift (e.g. sqlite:////tmp/test.db or postgresql+psycopg://... ). "
             "Used to build dblift_engine / dblift_client when no dblift_config fixture override.",
    )
    group.addoption(
        "--dblift-migrations-dir",
        action="store",
        default="migrations",
        help="Path to migrations directory (or comma-separated list).",
    )
    group.addoption(
        "--dblift-no-migrate",
        action="store_true",
        default=False,
        help="Skip automatic migration before tests (use dblift_migrated_db fixture explicitly if needed).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register dblift marker and load fixtures."""
    config.addinivalue_line(
        "markers", "dblift: marks tests as using dblift fixtures (provided by pytest-dblift)"
    )


# Load the fixtures module (will be populated in Task 4.2+).
# This makes fixtures like dblift_migrated_db available without explicit import.
pytest_plugins = ["pytest_dblift.fixtures"]