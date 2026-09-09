"""``run_command`` replays main()'s phases for one command and returns its JSON."""

from __future__ import annotations

import json
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
        # Deliberately not the runner's own fallback text: the point of the
        # assertion is that the raised message is carried through, not
        # replaced.
        raise CapabilityDeniedError("Feature requires a higher license tier")

    _install_fake_handler(monkeypatch, "info", denied)

    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(["--config", str(sqlite_project)], "info", [])

    assert "Feature requires a higher license tier" in str(exc_info.value)
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
def test_text_mode_output_includes_console_log_lines(sqlite_project, monkeypatch):
    """A text-mode command's real content is rendered through the console
    logger (stderr), not printed to stdout. ``output`` must carry both,
    stdout first, or an agent only ever sees the banner."""

    def logs_and_prints(ctx):
        print("DBLIFT COMMAND")
        ctx.log.info("DRIFT: widgets")
        return (True, None)

    _install_fake_handler(monkeypatch, "info", logs_and_prints)

    result = run_command(["--config", str(sqlite_project)], "info", [], json_argv=None)

    assert "DBLIFT COMMAND" in result["output"]
    assert "DRIFT: widgets" in result["output"]
    assert result["output"].index("DBLIFT COMMAND") < result["output"].index("DRIFT: widgets")


@pytest.mark.unit
def test_json_mode_output_never_carries_stderr(sqlite_project, monkeypatch):
    def logs_and_json(ctx):
        ctx.log.info("noisy console line that must not reach the payload")
        print(json.dumps({"success": True}))
        return (True, None)

    _install_fake_handler(monkeypatch, "info", logs_and_json)

    result = run_command(["--config", str(sqlite_project)], "info", [])

    assert result == {"success": True}


@pytest.mark.unit
def test_two_calls_do_not_duplicate_log_lines(sqlite_project, capsys):
    run_command(["--config", str(sqlite_project), "--log-level", "debug"], "info", [])
    first = capsys.readouterr().err.count("Using database name")
    run_command(["--config", str(sqlite_project), "--log-level", "debug"], "info", [])

    assert first == 1
    assert capsys.readouterr().err.count("Using database name") == 1


@pytest.mark.unit
def test_client_is_closed_after_the_call_even_when_the_handler_raises(sqlite_project, monkeypatch):
    from dblift.cli import main as cli_main

    client = MagicMock()
    monkeypatch.setattr(cli_main, "_build_command_client", lambda ctx: client)

    def boom(ctx):
        raise RuntimeError("handler exploded")

    _install_fake_handler(monkeypatch, "info", boom)

    with pytest.raises(CommandInvocationError):
        run_command(["--config", str(sqlite_project)], "info", [])

    client.close.assert_called_once_with()


@pytest.mark.unit
def test_client_is_closed_after_a_successful_call(sqlite_project, monkeypatch):
    from dblift.cli import main as cli_main

    client = MagicMock()
    monkeypatch.setattr(cli_main, "_build_command_client", lambda ctx: client)

    def ok(ctx):
        print(json.dumps({"success": True}))
        return (True, None)

    _install_fake_handler(monkeypatch, "info", ok)

    run_command(["--config", str(sqlite_project)], "info", [])

    client.close.assert_called_once_with()


@pytest.mark.unit
def test_unexpected_exception_becomes_invocation_error(sqlite_project, monkeypatch):
    def boom(ctx):
        raise RuntimeError("handler exploded")

    _install_fake_handler(monkeypatch, "info", boom)

    with pytest.raises(CommandInvocationError) as exc_info:
        run_command(["--config", str(sqlite_project)], "info", [])

    assert str(exc_info.value) == "RuntimeError: handler exploded"
    assert exc_info.value.exit_code == 1


@pytest.mark.unit
def test_keyboard_interrupt_propagates(sqlite_project, monkeypatch):
    def interrupt(ctx):
        raise KeyboardInterrupt

    _install_fake_handler(monkeypatch, "info", interrupt)

    with pytest.raises(KeyboardInterrupt):
        run_command(["--config", str(sqlite_project)], "info", [])
