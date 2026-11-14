"""A path that cannot be examined is reported as unreadable, never as absent.

From Python 3.14, ``Path.exists()`` and ``Path.is_file()`` return ``False`` for any
``OSError``; 3.11 to 3.13 raise ``PermissionError`` / ``OSError(ENAMETOOLONG)``. The
helpers in ``dblift.core.utils.path_checks`` raise on every version, and every site that
examines a user-named path uses them.
"""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.cli import _config_helpers
from dblift.cli.handlers import validate_sql
from dblift.cli.handlers._shared import CliCommandContext, ConfigOnlyClient
from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import load_config
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.utils.path_checks import path_exists, path_is_dir, path_is_file

pytestmark = pytest.mark.unit

NOT_ROOT = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can search any directory"
)


@pytest.fixture(params=["name-too-long", "directory-not-searchable"])
def unreadable(request, tmp_path: Path):
    """A path whose stat fails with an error other than 'not found'."""
    if request.param == "name-too-long":
        yield tmp_path / ("a" * 300)
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can search any directory")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "inside").write_text("x")
    locked.chmod(0)
    try:
        yield locked / "inside"
    finally:
        locked.chmod(0o700)


def test_helpers_report_present_and_absent_paths(tmp_path):
    file = tmp_path / "f.sql"
    file.write_text("x")
    assert path_exists(file) and path_is_file(file) and not path_is_dir(file)
    assert path_exists(tmp_path) and path_is_dir(tmp_path) and not path_is_file(tmp_path)
    assert not path_exists(tmp_path / "missing")
    assert not path_is_file(tmp_path / "missing") and not path_is_dir(tmp_path / "missing")
    assert not path_exists(file / "below-a-file")


def test_helpers_treat_a_dangling_symlink_and_a_nul_byte_as_absent(tmp_path):
    (tmp_path / "dangling").symlink_to(tmp_path / "nowhere")
    assert not path_exists(tmp_path / "dangling")
    assert not path_exists(Path("bad\x00name"))


def test_helpers_raise_when_the_path_cannot_be_examined(unreadable):
    for check in (path_exists, path_is_file, path_is_dir):
        with pytest.raises(OSError) as raised:
            check(unreadable)
        assert not isinstance(raised.value, FileNotFoundError)
    assert raised.value.errno in (errno.ENAMETOOLONG, errno.EACCES)


def test_builder_reports_an_unreadable_config_as_a_read_error(unreadable):
    with pytest.raises(OSError) as raised:
        ConfigBuilder.build(file_path=unreadable)
    assert not isinstance(raised.value, FileNotFoundError)
    assert "Config file not found" not in str(raised.value)


def test_builder_still_reports_a_missing_config_as_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        ConfigBuilder.build(file_path=tmp_path / "missing.yaml")


def test_load_config_reports_an_unreadable_config_as_a_load_error(unreadable):
    with pytest.raises(RuntimeError, match="Error loading config file"):
        load_config(str(unreadable))


def test_load_config_still_reports_a_missing_config_as_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(str(tmp_path / "missing.yaml"))


@NOT_ROOT
def test_default_config_discovery_does_not_skip_an_unreadable_directory(tmp_path, monkeypatch):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: locked))
    try:
        with pytest.raises(PermissionError):
            _config_helpers._discover_default_config()
    finally:
        locked.chmod(0o700)


def _scripts_args(**overrides) -> argparse.Namespace:
    values = dict(config=None, scripts_list=None, command="migrate")
    values.update(overrides)
    return argparse.Namespace(**values)


def _scripts_config() -> MagicMock:
    config = MagicMock()
    config.migrations.recursive = True
    config.migrations.get_directory_configs.return_value = []
    return config


def test_scripts_resolution_does_not_fall_back_when_the_config_path_is_unreadable(unreadable):
    parser = MagicMock()
    with pytest.raises(OSError) as raised:
        _config_helpers._resolve_scripts_directories(
            _scripts_args(config=str(unreadable)), _scripts_config(), parser, ["migrate"]
        )
    assert not isinstance(raised.value, FileNotFoundError)


@pytest.mark.parametrize("position", ["first", "additional"])
def test_scripts_resolution_says_cannot_read_not_not_found(unreadable, tmp_path, position):
    parser = MagicMock()
    parser.error.side_effect = SystemExit(2)
    listed = [str(unreadable)] if position == "first" else [str(tmp_path), str(unreadable)]
    with pytest.raises(SystemExit):
        _config_helpers._resolve_scripts_directories(
            _scripts_args(scripts_list=listed), _scripts_config(), parser, ["migrate"]
        )
    message = parser.error.call_args.args[0]
    assert "Cannot read" in message and "not found" not in message


def test_migration_directory_exists_raises_for_an_unreadable_directory(unreadable):
    with pytest.raises(OSError):
        MigrationScriptManager.migration_directory_exists(unreadable)


def test_migration_directory_exists_is_false_for_a_missing_directory(tmp_path):
    assert MigrationScriptManager.migration_directory_exists(tmp_path / "missing") is False


def test_collecting_scripts_does_not_skip_an_unreadable_directory(unreadable):
    manager = MigrationScriptManager(logger=MagicMock())
    with pytest.raises(OSError):
        manager.get_migration_scripts(unreadable)


def test_validate_sql_does_not_call_an_unreadable_file_not_found(unreadable):
    ctx = CliCommandContext(
        client=ConfigOnlyClient(
            config=SimpleNamespace(
                database=SimpleNamespace(type="postgresql"),
                migrations=SimpleNamespace(directory=""),
            )
        ),
        args=argparse.Namespace(files=[str(unreadable)], format="console"),
        log=MagicMock(),
    )
    try:
        _, result = validate_sql._handle_validate_sql(ctx)
    except OSError:
        return
    assert "File not found" not in str(getattr(result, "error_message", "") or "")
    assert result.success is False
