"""Main CLI module for dblift."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

# Add project root to Python path when running as a script
# This allows imports to work when running: python3 cli/main.py
# Get the project root (parent of cli directory)
_script_dir = Path(__file__).parent.absolute()
_project_root = _script_dir.parent.absolute()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from api import DBLiftClient
from core.logger import LogFactory
from core.utils.url_masking import mask_database_url

# Backward compatibility alias (used by tests and re-exports)
_mask_database_url = mask_database_url
from cli._command_handlers import (  # noqa: F401
    _AVAILABLE_COMMANDS,
    _COMMAND_HANDLERS,
    CliCommandContext,
    _extract_version_filters,
    _handle_baseline,
    _handle_clean,
    _handle_import_flyway,
    _handle_info,
    _handle_migrate,
    _handle_repair,
    _handle_undo,
    _handle_validate,
    _minimal_result,
    _set_command_completed,
    _validate_migrate_options,
    execute_single_command,
)
from cli._config_helpers import (  # noqa: F401
    _build_args_namespace,
    _close_logs,
    _collect_placeholders,
    _configure_logging,
    _ensure_connection,
    _extract_commands_from_argv,
    _load_and_merge_config,
    _resolve_scripts_directories,
    _validate_db_config,
    _validate_log_format_for_cli,
)
from cli._output import CommandOutput, from_args
from cli._parser_setup import (  # noqa: F401
    _add_baseline_options,
    _add_target_options,
    create_parser,
    parse_with_selective_errors,
)
from cli.extensions import load_terminal_commands

# Module-level placeholder; main() uses a local 'log' variable (no global declaration)
log = None

# argv tokens that are owned by the top-level parser only. Used by phase 1 to
# split the user-supplied argv between global flags and subcommand args. Lives
# at module level so the list is plain data, not entangled with parsing
# orchestration.
#
# Includes:
#  - tool-level flags (--version, log/db config),
#  - flags shared with subparsers that must be classified as global so they
#    are not swallowed by the next positional (BUG-01, B10-BUG-22, …),
#  - console-output toggles introduced by the Rich rollout (top-level only).
_GLOBAL_ONLY_ARGS: List[str] = [
    "--version",
    "--log-dir",
    "--log-format",
    "--log-level",
    "--log-file",
    "--db-url",
    "--db-username",
    "--db-password",
    "--db-schema",
    # --config/--scripts/--dry-run are defined on the top-level parser AND on most
    # subparsers. Classifying them as global lets `dblift --config F db check-connection`
    # work: without this, --config ends up in subcommand_args and the `db` parser
    # consumes its value as the `db_command` positional (BUG-01).
    "--config",
    "--scripts",
    "--dry-run",
    # B8-BUG-01: --recursive / --no-recursive live on the top-level parser
    # (mutually exclusive group in _parser_setup.py). Without marking them
    # global, they leak into subcommand_args and the subparser rejects them
    # as "unrecognized arguments".
    "--recursive",
    "--no-recursive",
    # Console-output toggles (Rich rollout). Top-level only — must
    # be classified as global so subparsers do not see them, and
    # registered as boolean in _GLOBAL_BOOLEAN_FLAGS so the
    # extractor does not treat the next token (the command name)
    # as their value.
    "--quiet",
    "-q",
    "--no-progress",
]

# Tool-level flag aliases for subcommands that take their own version-like
# argument. Used by the B10-BUG-04 footgun guard in phase 1 to redirect
# `dblift baseline --version 1.0.0` to the correct flag instead of
# short-circuiting through the global tool-version print.
_SUBCOMMAND_VERSION_ALIASES = {
    "baseline": "--baseline-version",
    "migrate": "--target-version",
    "undo": "--target-version",
    "validate": "--target-version",
}


@dataclass
class _CliContext:
    """Orchestration state passed between main()'s four phases.

    Built in :func:`_parse_argv_and_load_config`, finalised by
    :func:`_setup_logging_and_output`, and consumed by
    :func:`_dispatch_command`. Each field documents the phase that populates
    it so a maintainer adding a new field knows where to wire the assignment.
    """

    # Phase 1 — argv extraction and config load.
    commands: List[str]
    global_arguments: List[str]
    subcommand_args: List[str]
    args: Any  # argparse.Namespace; loose-typed so we don't pin the test surface.
    parser: Any  # argparse.ArgumentParser
    log: Any  # core.logger Log — bootstrap instance (re-assigned by phase 3).
    config: Optional[Any]  # config.DbliftConfig | None (None for `db` subcommands)


def main() -> None:
    """Main entry point for DBLift CLI application.

    Reads as a three-phase pipeline:

    1. Parse ``argv``, build the args namespace, load config, validate db
       config. Three terminal-action short-circuits live here (``--version``
       print, no-command help, extension terminal commands).
    2. Configure logging and build the :class:`CommandOutput`. Handles the
       ``db`` subcommand short-circuit before the logger is reconfigured.
    3. Dispatch the requested command(s) inside a try/except so any
       uncaught error gets logged and the logs are flushed.
    """
    from core.logger.console import install_rich_traceback

    install_rich_traceback()

    ctx = _parse_argv_and_load_config(sys.argv[1:])
    command_output = _setup_logging_and_output(ctx)
    exit_code = _dispatch_command(ctx, command_output)
    # Preserve the pre-refactor exit contract: return None on success so
    # the outer `sys.exit(main())` in the launcher script does not see a
    # raised SystemExit on the happy path. Tests that ``@patch("sys.exit")``
    # rely on the success path falling through instead of raising.
    if exit_code != 0:
        sys.exit(exit_code)


def _parse_argv_and_load_config(argv: List[str]) -> _CliContext:
    """Phase 1: extract commands, build args namespace, load config.

    Handles three terminal-action short-circuits via :func:`sys.exit` so
    the rest of the pipeline can assume ``ctx.commands[0]`` is the
    intended subcommand and ``ctx.args`` is a valid namespace:

    * ``--version``: print the tool version and exit ``0``.
    * No commands and no ``args.command``: print help and exit ``0``.
    * Extension terminal commands: dispatch and exit with their return code.
    """
    terminal_commands = load_terminal_commands()
    available_commands = list(dict.fromkeys(_AVAILABLE_COMMANDS + list(terminal_commands)))
    commands, global_arguments, subcommand_args = _extract_commands_from_argv(
        argv, available_commands, _GLOBAL_ONLY_ARGS
    )

    # B10-BUG-04: Flyway users type ``dblift baseline --version 1.0.0``
    # expecting to set the baseline version. Our ``--version`` flag is
    # global and short-circuits everything with the tool-version print —
    # the positional after it is silently dropped. Worse, for ``migrate``
    # / ``undo`` argparse then errors with "unrecognized arguments: 1.0.0"
    # which hides the real problem. Intercept the footgun *before* argparse
    # runs and point at the correct flag.
    if "--version" in global_arguments and commands:
        hint_cmd = commands[0]
        if hint_cmd in _SUBCOMMAND_VERSION_ALIASES:
            hint_flag = _SUBCOMMAND_VERSION_ALIASES[hint_cmd]
            CommandOutput("console").error(
                f"error: --version is the global tool-version flag. "
                f"To specify a version for '{hint_cmd}', use {hint_flag}."
            )
            sys.exit(2)

    if commands and commands[0] in terminal_commands:
        args = _build_terminal_args(commands[0], global_arguments, subcommand_args)
        if hasattr(args, "version") and args.version:
            from __init__ import __version__

            print(f"dblift version {__version__}")  # lint: allow-print  --version terminal action
            sys.exit(0)
        sys.exit(terminal_commands[commands[0]](args))

    args, _unknown_args = _build_args_namespace(commands, global_arguments, subcommand_args)

    if hasattr(args, "version") and args.version:
        from __init__ import __version__

        print(f"dblift version {__version__}")  # lint: allow-print  --version terminal action
        sys.exit(0)

    if not commands and (not hasattr(args, "command") or not args.command):
        create_parser().print_help()
        sys.exit(0)
    if not commands and hasattr(args, "command"):
        commands = [args.command]

    log = LogFactory.get_log("Dblift")
    parser = create_parser()
    # Validate log format before any config load so bogus --log-format fails with argparse
    # UX (and so db/* commands are covered — _validate_db_config skips early for "db").
    _validate_log_format_for_cli(args, parser)
    args.commands_list = commands
    config = None if commands[0] == "db" else _load_and_merge_config(args, log)
    _validate_db_config(args, config, parser, commands)

    return _CliContext(
        commands=commands,
        global_arguments=global_arguments,
        subcommand_args=subcommand_args,
        args=args,
        parser=parser,
        log=log,
        config=config,
    )


def _build_terminal_args(
    command: str, global_arguments: List[str], terminal_args: List[str]
) -> Any:
    """Parse top-level flags for terminal extensions that own their arguments."""
    args = create_parser().parse_args(global_arguments)
    args.command = command
    args.terminal_args = terminal_args
    return args


def _setup_logging_and_output(ctx: _CliContext) -> CommandOutput:
    """Phase 3: configure logging, build :class:`CommandOutput`.

    Handles the ``db`` subcommand short-circuit at the top: ``db`` commands
    run directly via ``args.func`` and exit, without needing the full
    logging configuration / banner setup that the migration workflow
    requires.

    Side effects: reassigns ``ctx.log`` to the fully-configured logger.
    """
    # Handle db utility commands (single command only, no chaining)
    if ctx.commands[0] == "db":
        if not hasattr(ctx.args, "db_command") or not ctx.args.db_command:
            if ctx.parser._subparsers is not None:
                for action in ctx.parser._subparsers._actions:
                    if action.dest == "command":
                        if hasattr(action, "choices") and isinstance(action.choices, dict):
                            db_parser = action.choices.get("db")
                            if db_parser:
                                db_parser.print_help()
            sys.exit(1)
        if hasattr(ctx.args, "func"):
            sys.exit(ctx.args.func(ctx.args))
        from_args(ctx.args).error(f"Unknown db command: {ctx.args.db_command}")
        sys.exit(1)

    assert ctx.config is not None
    ctx.log = _configure_logging(ctx.args, ctx.config, ctx.parser)

    # Banner routing is centralised in :class:`cli._output.CommandOutput`
    # (ADR-0008 supersedes ADR-0005's suppression approach). Machine
    # mode routes the banner to stderr; human mode keeps it on stdout.
    return from_args(ctx.args)


def _dispatch_command(ctx: _CliContext, command_output: CommandOutput) -> int:
    """Phase 4: build full workflow context and run the command loop.

    Returns the process exit code (``0`` success, ``1`` failure). Any
    uncaught exception is logged and the logs are flushed before the
    code is returned.
    """
    assert ctx.config is not None
    scripts_dir, additional_scripts_dirs, recursive, dir_recursive_map = (
        _resolve_scripts_directories(ctx.args, ctx.config, ctx.parser, ctx.commands)
    )

    client: DBLiftClient
    client = DBLiftClient.from_config(ctx.config, logger=ctx.log)
    ctx.log.debug(f"scripts_dir: {scripts_dir}")
    ctx.log.debug(
        f"config.migrations.directories: {getattr(ctx.config.migrations, 'directories', None)}"
    )

    placeholders = _collect_placeholders(ctx.args, ctx.config)
    if placeholders:
        ctx.log.debug(f"Using placeholders: {placeholders}")

    ctx.config.journal_enabled = True
    ctx.config.journal_dir = None
    if getattr(ctx.args, "strict", False):
        ctx.config.strict_mode = True
        ctx.log.info(
            "Strict mode is enabled. All migrations will be validated against strict rules."
        )

    try:
        any_command_failed = False
        from core.logger._formatters import TextFormatter

        database_name = getattr(ctx.config.database, "database_name", None) or getattr(
            ctx.config.database, "database", None
        )
        schema_name = getattr(ctx.config.database, "schema", None)
        formatter = TextFormatter()
        main_header = formatter.format_header(schema_name, database_name)

        from core.migration.commands import base_command

        if main_header:
            from core.migration.commands.base_command import _render_main_header_panel

            command_output.banner(_render_main_header_panel(main_header))
        # Always mark the header as printed so that _print_main_header_once()
        # in base_command does not re-emit it (it also has no format awareness).
        if main_header:
            base_command._console_main_header_printed = True  # type: ignore[attr-defined]

        for cmd_index, command in enumerate(ctx.commands):
            if len(ctx.commands) > 1 and cmd_index > 0:
                print("\n" + "=" * 80)  # lint: allow-print  multi-command separator
            if len(ctx.commands) > 1:
                cmd_argv = [sys.argv[0]] + ctx.global_arguments + [command] + ctx.subcommand_args
                original_argv_cmd = sys.argv.copy()
                sys.argv = cmd_argv
                try:
                    cmd_parser = create_parser(exit_on_error=False, suppress_errors=True)
                    cmd_args, cmd_unknown, has_error = parse_with_selective_errors(cmd_parser)
                    if has_error:
                        # argparse exits 2 on usage errors; preserve that for multi-command
                        # mode too (BUG-05).
                        sys.exit(2)
                    if cmd_args is None:
                        cmd_args = ctx.args
                finally:
                    sys.argv = original_argv_cmd
            else:
                cmd_args = ctx.args

            _ensure_connection(client, ctx.log, command)
            if command == "migrate":
                _validate_migrate_options(cmd_args, ctx.parser)

            if client is None:
                raise ValueError("Client is required for this command")
            success, result = execute_single_command(
                client=client,
                command=command,
                args=cmd_args,
                log=ctx.log,
                scripts_dir=scripts_dir,
                additional_scripts_dirs=additional_scripts_dirs,
                recursive=recursive,
                placeholders=placeholders,
                dir_recursive_map=dir_recursive_map,
            )
            if not success:
                any_command_failed = True
                break

        _close_logs(ctx.log)
        return 1 if any_command_failed else 0

    except Exception as e:
        ctx.log.error(f"Unexpected error: {str(e)}")
        ctx.log.error_with_exception("Command execution failed", e)
        _close_logs(ctx.log)
        return 1


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        sys.exit(e.code)
    except KeyboardInterrupt:
        # No args available here — fall back to a default CommandOutput.
        CommandOutput("console").error("\nOperation cancelled by user")
        sys.exit(130)
    except Exception as e:
        from core.logger.console import get_stderr_console

        console = get_stderr_console()
        console.print(f"Unexpected error: {e}", style="log.error")
        console.print_exception(show_locals=False, word_wrap=False)
        sys.exit(1)
