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


@pytest.fixture
def _clock(monkeypatch):
    """Freeze the log-file timestamp and advance it one second per read.

    The default file name is ``Dblift_<schema>_<db>_<%Y%m%d_%H%M%S>.log``, so
    two calls inside the same second would share a name and a naive test
    would pass before any change.
    """
    import datetime as real_datetime

    from dblift.core.logger import log as log_module

    ticks = iter(range(100))

    class Clock(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.datetime(2026, 9, 12, 12, 0, next(ticks), tzinfo=tz)

    monkeypatch.setattr(log_module, "datetime", Clock)


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


@pytest.mark.unit
def test_two_calls_share_one_text_log_file(sqlite_project, _clock):
    run_command([], "info", [])
    run_command([], "info", [])

    assert len(list((sqlite_project.parent / "logs").glob("*.log"))) == 1


@pytest.mark.unit
def test_json_log_format_keeps_one_file_per_call(sqlite_project, _clock):
    """JSON writes the complete log on close, so a shared file would clobber
    the previous call: the pin is TEXT-only."""
    run_command(["--log-format", "json"], "info", [])
    run_command(["--log-format", "json"], "info", [])

    assert len(list((sqlite_project.parent / "logs").glob("*.json"))) == 2


@pytest.mark.unit
def test_user_supplied_log_file_pattern_is_expanded_once(sqlite_project, _clock):
    """``<timestamp>`` in a user ``--log-file`` expands on the first call and
    the resolved path is reused, not re-expanded per call."""
    argv = ["--log-file", "custom_<timestamp>.log"]

    run_command(argv, "info", [])
    after_first = sorted(p.name for p in (sqlite_project.parent / "logs").glob("custom_*.log"))
    run_command(argv, "info", [])

    assert len(after_first) == 1
    assert sorted(p.name for p in (sqlite_project.parent / "logs").glob("custom_*.log")) == (
        after_first
    )


@pytest.mark.unit
def test_a_deleted_log_file_is_not_recreated(sqlite_project, _clock):
    """Deleting the pinned file unpins it: later calls open and then share a
    fresh file, and the deleted path is never written back."""
    logs = sqlite_project.parent / "logs"
    run_command([], "info", [])
    run_command([], "info", [])
    (pinned,) = logs.glob("*.log")
    pinned.unlink()

    run_command([], "info", [])
    assert not pinned.exists()

    # The re-opening call also leaves behind the file the config load opens
    # before the call configures its own logging — pre-existing behaviour for
    # any unpinned call, so the count is not asserted. What must hold is that
    # the new file is pinned in turn: the call after it adds nothing.
    after_reopen = sorted(path.name for path in logs.glob("*.log"))
    run_command([], "info", [])

    assert sorted(path.name for path in logs.glob("*.log")) == after_reopen


@pytest.mark.unit
def test_an_additional_file_format_keeps_one_text_file_per_call(sqlite_project, _clock):
    """``text,html`` opens a second file sink that takes the same pattern, so
    the pin must not apply: sharing it would let the HTML sink rewrite the
    text log."""
    logs = sqlite_project.parent / "logs"

    run_command(["--log-format", "text,html"], "info", [])
    after_first = sorted(path.name for path in logs.glob("*.log"))
    run_command(["--log-format", "text,html"], "info", [])

    assert len(after_first) == 1
    # More than one, not exactly two: an unpinned call also opens a file while
    # the config loads, before its own logging is configured.
    assert len(list(logs.glob("*.log"))) > 1


@pytest.mark.unit
def test_a_call_asking_for_another_format_is_not_forced_onto_the_pinned_file(
    sqlite_project, _clock
):
    """The reuse is TEXT-only in both directions: a later JSON call writes its
    own file instead of overwriting the text log the pin accumulated."""
    logs = sqlite_project.parent / "logs"

    run_command([], "info", [])
    (pinned,) = logs.glob("*.log")
    text_so_far = pinned.read_text()

    run_command(["--log-format", "json"], "info", [])

    assert [path.name for path in logs.glob("*.log")] == [pinned.name]
    assert pinned.read_text().startswith(text_so_far)
    assert not pinned.read_text().lstrip().startswith(("{", "["))
    assert len(list(logs.glob("*.json"))) == 1

    # The pin survives the interruption: the next text call appends to it.
    run_command([], "info", [])

    assert [path.name for path in logs.glob("*.log")] == [pinned.name]
    assert len(pinned.read_text()) > len(text_so_far)
