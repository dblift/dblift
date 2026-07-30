"""Tests for resolve_dblift_package_version (release banner)."""

from __future__ import annotations

import pytest

from core.logger._formatters import resolve_dblift_package_version


@pytest.mark.unit
def test_resolve_version_matches_installed_dblift():
    from importlib.metadata import version

    resolved = resolve_dblift_package_version()
    assert resolved is not None
    assert resolved == version("dblift")
