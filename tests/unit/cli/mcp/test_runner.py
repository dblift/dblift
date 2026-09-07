"""``run_command`` replays main()'s phases for one command and returns its JSON."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from dblift.cli.mcp.runner import CommandInvocationError, run_command
from dblift.core.seams.capabilities import CapabilityDeniedError


@pytest.fixture
def sqlite_project(tmp_path, monkeypatch):
    """A dblift.yaml + one migration on SQLite, returned as the config path.

    ``chdir`` so the CLI's default ``logs/`` directory lands in ``tmp_path``.
    """
    monkeypatch.chdir(tmp_path)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "t.sqlite")},
                "migrations": {"directory": str(migrations)},
            }
        )
    )
    return config


def _install_fake_handler(monkeypatch, name, fn):
    from dblift.cli import _command_handlers, main

    table = dict(_command_handlers._COMMAND_HANDLERS)
    table[name] = fn
    monkeypatch.setattr(_command_handlers, "_COMMAND_HANDLERS", table)
    monkeypatch.setattr(main, "_COMMAND_HANDLERS", table)


@pytest.mark.unit
def test_run_command_returns_parsed_json_and_leaks_nothing_to_stdout(sqlite_project, capsys):
    result = run_command(["--config", str(sqlite_project)], "info", [])

    assert result["success"] is True
    assert result["migrations"][0]["script"] == "V1__init.sql"
    assert capsys.readouterr().out == ""


@pytest.mark.unit
def test_run_command_prepends_global_argv(sqlite_project, monkeypatch):
    seen = {}

    def fake(ctx):
        seen["config"] = ctx.args.config
        print(json.dumps({"success": True}))
        return (True, None)

    _install_fake_handler(monkeypatch, "info", fake)

    run_command(["--config", str(sqlite_project)], "info", [])

    assert seen["config"] == str(sqlite_project)


@pytest.mark.unit
def test_capability_denied_becomes_invocation_error_with_cli_message(sqlite_project, monkeypatch):
    def denied(ctx):
        raise CapabilityDeniedError("Plan requires an ENTERPRISE license (current: NONE)")

    _install_fake_handler(monkeypatch, "info", denied)

    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(["--config", str(sqlite_project)], "info", [])

    assert "Plan requires an ENTERPRISE license" in str(exc_info.value)
    assert exc_info.value.exit_code == 4


@pytest.mark.unit
@pytest.mark.parametrize("code", [1, 2, 78])
def test_systemexit_inside_handler_is_contained(sqlite_project, monkeypatch, code):
    def exits(ctx):
        raise SystemExit(code)

    _install_fake_handler(monkeypatch, "info", exits)

    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(["--config", str(sqlite_project)], "info", [])

    assert exc_info.value.exit_code == code


@pytest.mark.unit
def test_config_error_is_contained(tmp_path):
    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(["--config", str(tmp_path / "missing.yaml")], "info", [])

    assert exc_info.value.exit_code == 1


@pytest.mark.unit
def test_non_json_stdout_is_reported_not_swallowed(sqlite_project, monkeypatch):
    def chatty(ctx):
        print("not json")
        return (True, None)

    _install_fake_handler(monkeypatch, "info", chatty)

    with pytest.raises(CommandInvocationError, match="not json"):
        run_command(["--config", str(sqlite_project)], "info", [])


@pytest.mark.unit
def test_text_mode_returns_success_and_output(sqlite_project, monkeypatch):
    def texty(ctx):
        print("exported 3 objects")
        return (True, None)

    _install_fake_handler(monkeypatch, "info", texty)

    result = run_command(["--config", str(sqlite_project)], "info", [], json_argv=None)

    assert result == {"success": True, "output": "exported 3 objects"}


@pytest.mark.unit
def test_migrate_option_validation_runs(sqlite_project):
    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(
            ["--config", str(sqlite_project)],
            "migrate",
            ["--dry-run", "--target-version", "1", "--versions", "1"],
        )

    assert exc_info.value.exit_code == 2
    assert "Cannot specify both" in str(exc_info.value)


@pytest.mark.unit
def test_two_calls_do_not_duplicate_log_lines(sqlite_project, capsys):
    run_command(["--config", str(sqlite_project), "--log-level", "debug"], "info", [])
    first = capsys.readouterr().err.count("Using database name")
    run_command(["--config", str(sqlite_project), "--log-level", "debug"], "info", [])

    assert first == 1
    assert capsys.readouterr().err.count("Using database name") == 1
