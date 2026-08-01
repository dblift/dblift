"""Tests for resolve_dblift_package_version (release banner)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest

from core.logger._formatters import resolve_dblift_package_version


def _read_version_line(init_file: Path) -> str:
    for line in init_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise AssertionError(f"no __version__ line in {init_file}")


@pytest.mark.unit
def test_resolve_version_matches_running_source():
    """Ground truth is the running source's own ``__init__.py``, not whatever
    ``importlib.metadata`` happens to resolve — a same-named distribution
    installed elsewhere on ``sys.path`` (or a stale editable-install record)
    must not shadow the code that is actually executing."""
    import core.logger._formatters as formatters_module

    repo_root_init = Path(formatters_module.__file__).resolve().parent.parent.parent / "__init__.py"
    expected = _read_version_line(repo_root_init)

    resolved = resolve_dblift_package_version()

    assert resolved == expected


@pytest.mark.unit
def test_resolve_version_prefers_bundled_init_over_shadowed_metadata(tmp_path, monkeypatch):
    """A same-named ``dblift`` distribution earlier on ``sys.path`` (e.g. a
    stale global install, or an editable install's dist-info left unrefreshed
    since a later version bump) must not shadow the version actually bundled
    with the running code."""
    (tmp_path / "__init__.py").write_text('__version__ = "9.9.9-bundled"\n', encoding="utf-8")
    fake_formatters_file = tmp_path / "core" / "logger" / "_formatters.py"

    monkeypatch.setattr("core.logger._formatters.__file__", str(fake_formatters_file))
    monkeypatch.setattr("sys.frozen", False, raising=False)

    def _shadowed_version(name):
        if name == "dblift":
            return "0.0.1-shadowed"
        raise PackageNotFoundError(name)

    with patch("importlib.metadata.version", _shadowed_version):
        resolved = resolve_dblift_package_version()

    assert resolved == "9.9.9-bundled"


@pytest.mark.unit
def test_resolve_version_prefers_metadata_when_frozen(tmp_path, monkeypatch):
    """Under PyInstaller, ``__file__`` resolves under the MEIPASS extraction
    layout rather than a real source tree, so a bundled ``__init__.py``
    filesystem walk is unreliable there — ``importlib.metadata`` must win."""
    (tmp_path / "__init__.py").write_text('__version__ = "9.9.9-bundled"\n', encoding="utf-8")
    fake_formatters_file = tmp_path / "core" / "logger" / "_formatters.py"

    monkeypatch.setattr("core.logger._formatters.__file__", str(fake_formatters_file))
    monkeypatch.setattr("sys.frozen", True, raising=False)

    def _frozen_version(name):
        if name == "dblift":
            return "1.2.3-frozen"
        raise PackageNotFoundError(name)

    with patch("importlib.metadata.version", _frozen_version):
        resolved = resolve_dblift_package_version()

    assert resolved == "1.2.3-frozen"
