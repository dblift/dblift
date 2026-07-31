"""Coverage for CLI dispatch strict_mode and SystemExit flush paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import cli.main as cli_main
from cli._constants import EXIT_LICENSE_REQUIRED
from cli._output import CommandOutput


def _ctx(*, strict_on_args: bool = False, strict_on_config: bool = False):
    log = MagicMock()
    config = MagicMock()
    config.strict_mode = strict_on_config
    config.database = SimpleNamespace(database_name="db", schema="public", database=None)
    config.migrations = SimpleNamespace(directories=None)
    args = MagicMock()
    args.strict_mode = strict_on_args
    return cli_main._CliContext(
        commands=["info"],
        global_arguments=[],
        subcommand_args=[],
        args=args,
        parser=MagicMock(),
        log=log,
        config=config,
    )


@pytest.mark.unit
def test_dispatch_honors_strict_mode_from_args():
    ctx = _ctx(strict_on_args=True)
    output = CommandOutput("table")

    with (
        patch.object(
            cli_main,
            "_resolve_scripts_directories",
            return_value=("/migs", [], True, {}),
        ),
        patch.object(cli_main, "_build_command_client", return_value=MagicMock()),
        patch.object(cli_main, "_collect_placeholders", return_value={}),
        patch.object(cli_main, "_ensure_connection"),
        patch.object(cli_main, "execute_single_command", return_value=(True, MagicMock())),
        patch.object(cli_main, "_close_logs") as close_logs,
        patch("core.logger._formatters.TextFormatter") as formatter_cls,
    ):
        formatter_cls.return_value.format_header.return_value = None
        code = cli_main._dispatch_command(ctx, output)

    assert code == 0
    assert ctx.config.strict_mode is True
    ctx.log.info.assert_any_call(
        "Strict mode is enabled. All migrations will be validated against strict rules."
    )
    close_logs.assert_called()


@pytest.mark.unit
def test_dispatch_system_exit_flushes_logs_and_reraises():
    ctx = _ctx()
    output = CommandOutput("table")

    with (
        patch.object(
            cli_main,
            "_resolve_scripts_directories",
            return_value=("/migs", [], True, {}),
        ),
        patch.object(cli_main, "_build_command_client", return_value=MagicMock()),
        patch.object(cli_main, "_collect_placeholders", return_value={}),
        patch.object(cli_main, "_ensure_connection"),
        patch.object(
            cli_main,
            "execute_single_command",
            side_effect=SystemExit(EXIT_LICENSE_REQUIRED),
        ),
        patch.object(cli_main, "_close_logs") as close_logs,
        patch("core.logger._formatters.TextFormatter") as formatter_cls,
    ):
        formatter_cls.return_value.format_header.return_value = None
        with pytest.raises(SystemExit) as excinfo:
            cli_main._dispatch_command(ctx, output)

    assert excinfo.value.code == EXIT_LICENSE_REQUIRED
    close_logs.assert_called()
