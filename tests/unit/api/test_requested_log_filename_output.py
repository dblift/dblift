"""The API writes the requested filename and expands timestamp placeholders."""

import re

import pytest

from dblift.api.client import DBLiftClient
from tests.unit.api.test_requested_log_file_api import _project
from tests.unit.cli.test_requested_log_file_cli import _files

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    "extra",
    ["log_file: requested.log\n", "logging:\n  file: requested.log\n"],
    ids=["flat", "nested"],
)
def test_api_config_relative_filename_is_exact_and_contains_output(tmp_path, monkeypatch, extra):
    config = _project(tmp_path, extra)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
        client.logger.info("requested filename regression marker")
        client.migrate()
    target = config.parent / "requested.log"
    assert _files(tmp_path) == [target]
    assert "requested filename regression marker" in target.read_text()
    assert list(elsewhere.iterdir()) == []


def test_api_argument_filename_is_exact_in_the_working_directory(tmp_path, monkeypatch):
    config = _project(tmp_path, "")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with DBLiftClient.from_config_file(str(config), log_file="requested.log") as client:
        client.logger.info("requested argument regression marker")
    target = elsewhere / "requested.log"
    assert _files(tmp_path) == [target]
    assert "requested argument regression marker" in target.read_text()
    assert not (elsewhere / "logs").exists()


def test_api_timestamp_pattern_is_expanded_in_the_actual_output_file(tmp_path, monkeypatch):
    config = _project(tmp_path, "")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with DBLiftClient.from_config_file(
        str(config), log_file="out/<timestamp>/requested-<timestamp>.log"
    ) as client:
        client.logger.info("requested timestamp regression marker")
    logs = _files(tmp_path)
    assert len(logs) == 1
    relative = logs[0].relative_to(elsewhere)
    assert re.fullmatch(r"out/(\d{8}_\d{6})/requested-\1\.log", relative.as_posix())
    assert "requested timestamp regression marker" in logs[0].read_text()
    assert not (elsewhere / "out" / "<timestamp>").exists()


def test_api_absolute_filename_does_not_create_an_unused_configured_directory(tmp_path):
    config = _project(tmp_path, "logging:\n  directory: unused\n")
    target = tmp_path / "actual" / "requested.log"
    with DBLiftClient.from_config_file(
        str(config), relative_to_config=True, log_file=str(target)
    ) as client:
        client.logger.info("requested absolute filename regression marker")
    assert _files(tmp_path) == [target]
    assert "requested absolute filename regression marker" in target.read_text()
    assert not (config.parent / "unused").exists()
