"""``create_release`` must accept PEP 440 pre-release versions (aN, bN, rcN).

The version check and both substitutions used to hard-code ``x.y.z``, so
``5.0.0a1`` was refused outright and, once past the check, a pre-release
already in the tree could not be replaced by the next one.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "create_release.py"


def _load():
    spec = importlib.util.spec_from_file_location("_create_release_pre", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_tree(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "dblift"\n'
        f'version = "{version}"\n'
        'classifiers = ["Development Status :: 5 - Production/Stable"]\n'
    )
    package = root / "dblift"
    package.mkdir()
    (package / "__init__.py").write_text(f'__version__ = "{version}"\n')


@pytest.mark.parametrize("version", ["5.0.0a1", "5.0.0b2", "5.0.0rc1", "4.12.0", "10.0.0a12"])
def test_valid_versions_are_accepted(version):
    assert _load().validate_version(version) is True


@pytest.mark.parametrize(
    "version",
    ["5.0", "5.0.0a", "5.0.0a1.dev1", "5.0.0-alpha.1", "v5.0.0", "5.0.0c1", "5.0.0.post1", ""],
)
def test_invalid_versions_are_refused(version, capsys):
    assert _load().validate_version(version) is False
    assert "Version must be" in capsys.readouterr().out


@pytest.mark.parametrize("old", ["4.12.0", "5.0.0a1"])
@pytest.mark.parametrize("new", ["5.0.0a1", "5.0.0a2", "5.0.0rc1", "5.0.0"])
def test_both_version_sites_are_replaced_whole(tmp_path, monkeypatch, old, new):
    if old == new:
        pytest.skip("re-writing the same version is reported as 'no version line'")
    _write_tree(tmp_path, old)
    monkeypatch.chdir(tmp_path)

    assert _load().update_version_in_files(new) is True

    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert f'\nversion = "{new}"\n' in pyproject
    assert f'__version__ = "{new}"\n' == (tmp_path / "dblift" / "__init__.py").read_text()


def test_a_pre_release_keeps_the_classifier(tmp_path, monkeypatch):
    """Alpha packaging work ships under the existing classifier; the script
    never rewrites trove classifiers."""
    _write_tree(tmp_path, "4.12.0")
    monkeypatch.chdir(tmp_path)

    _load().update_version_in_files("5.0.0a1")

    assert (
        "Development Status :: 5 - Production/Stable" in (tmp_path / "pyproject.toml").read_text()
    )


def test_dry_run_of_a_pre_release_passes():
    done = subprocess.run(
        [sys.executable, str(_SCRIPT), "--dry-run", "5.0.0a1"],
        cwd=_SCRIPT.parents[1],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
