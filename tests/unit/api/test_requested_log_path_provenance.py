"""API logging overrides retain their invocation-relative source."""

import pytest

from dblift.api.client import DBLiftClient
from tests.unit.api.test_requested_log_file_api import _project
from tests.unit.cli.test_requested_log_file_cli import _files

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("source", ["argument", "environment"])
@pytest.mark.parametrize("filename", ["requested.log", "own/requested.log"])
def test_api_explicit_filename_is_not_anchored_by_relative_to_config(
    tmp_path, monkeypatch, source, filename
):
    config = _project(tmp_path, f"logging:\n  file: {filename}\n")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    overrides = {"log_file": filename} if source == "argument" else {}
    if source == "environment":
        monkeypatch.setenv("DBLIFT_LOG_FILE", filename)
    with DBLiftClient.from_config_file(str(config), relative_to_config=True, **overrides) as client:
        client.logger.info("explicit filename source marker")
    target = work / filename
    assert _files(tmp_path) == [target]
    assert "explicit filename source marker" in target.read_text()


@pytest.mark.parametrize("source", ["argument", "environment"])
def test_api_directory_only_override_preserves_configured_bare_filename(
    tmp_path, monkeypatch, source
):
    config = _project(tmp_path, "logging:\n  file: requested.log\n")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    overrides = {"log_dir": "override"} if source == "argument" else {}
    if source == "environment":
        monkeypatch.setenv("DBLIFT_LOG_DIR", "override")
    with DBLiftClient.from_config_file(str(config), relative_to_config=True, **overrides) as client:
        client.logger.info("directory override source marker")
    target = work / "override" / "requested.log"
    assert _files(tmp_path) == [target]
    assert "directory override source marker" in target.read_text()
