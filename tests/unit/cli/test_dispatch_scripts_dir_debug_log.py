"""Regression test for issue #833: DEBUG scripts_dir trace line accuracy.

``_dispatch_command`` used to log the locally-resolved ``scripts_dir`` value
returned by ``_resolve_scripts_directories`` (resolved against the config
file's parent directory). The client actually used for scanning re-resolves
the migrations directory independently from config (resolved against the
current working directory at scan time via ``Path.resolve()``), so the two
values can disagree when a relative ``migrations.directories`` path is
combined with ``--config`` pointing somewhere other than the CWD. The debug
line must report the directory the client actually scans, not the
separately-computed local value.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import cli.main as cli_main
from cli._output import CommandOutput


def _ctx():
    log = MagicMock()
    config = MagicMock()
    config.strict_mode = False
    config.database = SimpleNamespace(database_name="db", schema="public", database=None)
    config.migrations = SimpleNamespace(directories=None)
    args = MagicMock()
    args.strict_mode = False
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
def test_dispatch_logs_client_scripts_dir_not_stale_local_value(tmp_path):
    """The logged scripts_dir must match the client's actual scan directory."""
    ctx = _ctx()
    output = CommandOutput("table")

    # A value that _resolve_scripts_directories computed locally (e.g.
    # resolved against a --config file's parent directory) but that was
    # never actually scanned.
    stale_unresolved_dir = tmp_path / "config_dir" / "migrations"

    # The directory the client actually resolves and scans (e.g. CWD-relative
    # resolution performed independently inside client construction).
    real_scanned_dir = tmp_path / "cwd_dir" / "migrations"
    real_scanned_dir.mkdir(parents=True)

    client = MagicMock()
    client._get_scripts_dir.return_value = real_scanned_dir

    with (
        patch.object(
            cli_main,
            "_resolve_scripts_directories",
            return_value=(stale_unresolved_dir, [], True, {}),
        ),
        patch.object(cli_main, "_build_command_client", return_value=client),
        patch.object(cli_main, "_collect_placeholders", return_value={}),
        patch.object(cli_main, "_ensure_connection"),
        patch.object(cli_main, "execute_single_command", return_value=(True, MagicMock())),
        patch.object(cli_main, "_close_logs"),
        patch("core.logger._formatters.TextFormatter") as formatter_cls,
    ):
        formatter_cls.return_value.format_header.return_value = None
        cli_main._dispatch_command(ctx, output)

    logged = [c.args[0] for c in ctx.log.debug.call_args_list if c.args]
    scripts_dir_lines = [line for line in logged if line.startswith("scripts_dir:")]

    assert scripts_dir_lines, "expected a 'scripts_dir:' debug line"
    assert scripts_dir_lines[0] == f"scripts_dir: {real_scanned_dir.resolve()}"
    assert str(stale_unresolved_dir) not in scripts_dir_lines[0]
