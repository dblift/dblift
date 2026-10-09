"""The two built distributions preserve one owner for every Python file."""

import configparser
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    output = tmp_path_factory.mktemp("distribution-profiles")
    for source in (ROOT, ROOT / "packages" / "dblift"):
        assert (source / "pyproject.toml").is_file(), f"missing distribution project: {source}"
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(output), str(source)],
            check=True,
            capture_output=True,
            text=True,
        )
    return {path.name.split("-", 1)[0]: path for path in output.glob("*.whl")}


def _wheel_metadata(path):
    with zipfile.ZipFile(path) as archive:
        files = set(archive.namelist())
        metadata_file = next(name for name in files if name.endswith(".dist-info/METADATA"))
        message = Parser().parsestr(archive.read(metadata_file).decode())
        entries_file = next(
            (name for name in files if name.endswith(".dist-info/entry_points.txt")), None
        )
        entries = configparser.ConfigParser()
        if entries_file:
            entries.read_string(archive.read(entries_file).decode())
    return files, message, entries


def test_core_owns_code_and_bundle_owns_console(wheels):
    assert set(wheels) == {"dblift_core", "dblift"}
    core_files, core, core_entries = _wheel_metadata(wheels["dblift_core"])
    bundle_files, bundle, bundle_entries = _wheel_metadata(wheels["dblift"])
    assert core["Name"] == "dblift-core"
    assert bundle["Name"] == "dblift"
    assert core["Version"] == bundle["Version"]
    assert "dblift/py.typed" in core_files
    assert "dblift/core/logger/templates/report.html" in core_files
    assert not any(name.startswith("dblift/") for name in bundle_files)
    assert not core_entries.has_section("console_scripts")
    assert dict(bundle_entries.items("console_scripts")) == {
        "dblift": "dblift.cli.main:main"
    }
    for group in ("dblift.providers", "dblift.provider_descriptors"):
        assert core_entries.has_section(group)
        assert not bundle_entries.has_section(group)


def test_minimal_and_standard_requirements(wheels):
    _, core, _ = _wheel_metadata(wheels["dblift_core"])
    _, bundle, _ = _wheel_metadata(wheels["dblift"])
    core_reqs = [Requirement(value) for value in core.get_all("Requires-Dist", [])]
    plain = {req.name.lower() for req in core_reqs if req.marker is None}
    assert plain == {"pyyaml", "sqlalchemy"}
    extras = {name.lower(): set() for name in core.get_all("Provides-Extra", [])}
    for requirement in core_reqs:
        for extra in extras:
            if requirement.marker and requirement.marker.evaluate({"extra": extra}):
                extras[extra].add(requirement.name.lower())
    assert {"sqlglot"} <= extras["analysis"]
    assert {"rich", "jinja2"} <= extras["presentation"]
    bundle_reqs = [Requirement(value) for value in bundle.get_all("Requires-Dist", [])]
    assert len([req for req in bundle_reqs if req.marker is None]) == 1
    standard = next(req for req in bundle_reqs if req.marker is None)
    assert standard.name == "dblift-core"
    assert standard.extras == {"analysis", "presentation"}
    assert str(standard.specifier) == f"=={bundle['Version']}"
