"""``create_release.update_version_in_files`` must bump every version site.

Cutting 4.0.0 found the function pointing at a repo-root ``__init__.py`` that
the namespace move had turned into ``dblift/__init__.py``. The block guarded
the read with ``if init_py.exists()`` and had no ``else``, so the bump was
skipped in silence: ``pyproject.toml`` said 4.0.0 while ``dblift.__version__``
still said 3.10.1, and nothing in the release run said otherwise.
"""

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "create_release.py"


def _load_create_release():
    spec = importlib.util.spec_from_file_location("_create_release", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_tree(root: Path, version: str = "3.10.1") -> None:
    (root / "pyproject.toml").write_text(f'[project]\nname = "dblift"\nversion = "{version}"\n')
    package = root / "dblift"
    package.mkdir()
    (package / "__init__.py").write_text(f'"""DBLift."""\n\n__version__ = "{version}"\n')


def test_bumps_both_the_pyproject_and_the_package_marker(tmp_path, monkeypatch):
    _write_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert _load_create_release().update_version_in_files("4.0.0") is True

    assert 'version = "4.0.0"' in (tmp_path / "pyproject.toml").read_text()
    assert '__version__ = "4.0.0"' in (tmp_path / "dblift" / "__init__.py").read_text()


def test_reports_failure_when_the_package_marker_is_missing(tmp_path, monkeypatch, capsys):
    """The regression itself: a missing marker must not pass as success.

    Without this, a future layout change repeats the 4.0.0 near-miss — the
    run prints a bumped pyproject, returns success, and ships a package whose
    ``__version__`` is a release behind.
    """
    _write_tree(tmp_path)
    os.remove(tmp_path / "dblift" / "__init__.py")
    monkeypatch.chdir(tmp_path)

    assert _load_create_release().update_version_in_files("4.0.0") is False
    assert "not found" in capsys.readouterr().out
