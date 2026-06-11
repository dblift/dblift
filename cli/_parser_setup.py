"""Parser setup functions for the dblift CLI.

Extracted from cli/main.py (story 20-16) to reduce file size.
Contains the 7 argparse configuration functions.
"""

import argparse
import io
import sys
from typing import Any, Dict, List, Optional, Tuple

from cli.db_utils import setup_db_utils_parser
from cli.extensions import load_command_extensions


def parse_with_selective_errors(
    parser: argparse.ArgumentParser,
) -> Tuple[Optional[argparse.Namespace], List[str], bool]:
    """
    Parse arguments, capturing stderr and filtering out only "unrecognized arguments" messages.
    Other validation errors (invalid choices, missing required args, etc.) are shown.

    Returns:
        tuple: (args, unknown_args, has_error) where has_error indicates a real validation error
    """
    # Capture stderr during parsing
    old_stderr = sys.stderr
    captured_stderr = io.StringIO()
    sys.stderr = captured_stderr

    args = None
    unknown_args: List[str] = []
    parse_exception = None

    try:
        args, unknown_args = parser.parse_known_args()
    except (argparse.ArgumentError, SystemExit, Exception) as e:
        parse_exception = e
    finally:
        sys.stderr = old_stderr

    # Get captured error messages
    error_output = captured_stderr.getvalue()

    # Filter stderr: only show messages that are NOT about unrecognized arguments
    if error_output:
        lines = error_output.strip().split("\n")
        filtered_lines = []

        for line in lines:
            # Skip lines about unrecognized arguments (these are expected in multi-command mode)
            if "unrecognized arguments:" in line.lower():
                continue
            # Skip usage lines that appear with unrecognized args errors
            if line.startswith("usage:") and any(
                "unrecognized arguments:" in ln.lower() for ln in lines
            ):
                continue
            # Show all other error messages (invalid choices, type errors, etc.)
            filtered_lines.append(line)

        # Print filtered errors
        if filtered_lines:
            print("\n".join(filtered_lines), file=sys.stderr)
            return args, unknown_args, True  # Has real validation error

    # If there was a parse exception but no error output, it might be a silent error
    if parse_exception and not error_output:
        return args, unknown_args, True

    return args, unknown_args, False  # No validation errors


def _make_history_table_parent() -> argparse.ArgumentParser:
    """Parent parser for the ``--table`` history-table override.

    Inherited by migrate, undo, clean, validate, info, diff, repair,
    import-flyway, and baseline. Defining it once via ``parents=[...]``
    makes the duplication visible to the type-checker and removes the
    ``for subparser in [...]`` loop that used to add it imperatively.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--table",
        dest="table_name",
        help="Custom schema history table name (default: dblift_schema_history)",
    )
    return p


def _make_snapshot_table_parent() -> argparse.ArgumentParser:
    """Parent parser for commands that read or write persisted schema snapshots."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--snapshot-table",
        dest="snapshot_table",
        help="Custom schema snapshot table name (default: dblift_schema_snapshots)",
    )
    return p


def _make_strict_parent() -> argparse.ArgumentParser:
    """Parent parser for the ``--strict`` flag (not exposed by import-flyway)."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument(
        "--strict",
        action="store_true",
        help="Enable strict mode - fail if any previously applied migration is missing "
        "and require migrations to be applied in strict version order",
    )
    return p


def _make_filter_parent() -> argparse.ArgumentParser:
    """Parent parser for tag/version/placeholder filters.

    Inherited by migrate, undo, validate, info, diff.
    """
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--tags", help="Execute migrations with specified tags (comma-separated list)")
    p.add_argument(
        "--exclude-tags", help="Skip migrations with specified tags (comma-separated list)"
    )
    p.add_argument("--versions", help="Execute only specific versions (comma-separated list)")
    p.add_argument("--exclude-versions", help="Skip specific versions (comma-separated list)")
    p.add_argument(
        "--placeholders",
        nargs="+",
        action="append",
        help="SQL placeholders for variable substitution in migration scripts. "
        "Format: key1=value1,key2=value2 or key1=value1 key2=value2. "
        "Can be repeated: --placeholders k1=v1 --placeholders k2=v2",
    )
    return p


# NOTE: ``--target-version`` is intentionally NOT extracted into a parent
# parser. Its help text is genuinely command-specific (migrate / undo /
# diff each describe a different intent) and unifying it would degrade
# `--help` output. Each subparser adds it explicitly in
# ``_add_diff_and_target_options`` so the user-facing string stays
# accurate. See Bugbot review on PR-09.


def _add_baseline_options(baseline_parser: argparse.ArgumentParser) -> None:
    """Configure arguments specific to the baseline command.

    ``--table`` is inherited via the history-table parent parser in
    :func:`create_parser`; this function now only adds baseline-exclusive
    flags.
    """
    # Note: no ``--version`` alias here. ``cli/main.py`` classifies ``--version``
    # as a global-only arg and intercepts it before subparsers see it — the
    # top-level ``--version`` flag prints the tool version and exits. Adding
    # ``--version`` here would be silently dead: ``dblift baseline --version
    # 1.0.0`` would print the dblift version instead of baselining.
    baseline_parser.add_argument(
        "--baseline-version",
        dest="baseline_version",
        help="Version to baseline the database at",
        required=True,
    )
    baseline_parser.add_argument(
        "--baseline-description", help="Description for the baseline version"
    )


def _add_diff_and_target_options(
    migrate_parser: argparse.ArgumentParser,
    undo_parser: argparse.ArgumentParser,
    validate_parser: argparse.ArgumentParser,
    clean_parser: argparse.ArgumentParser,
) -> None:
    """Configure diff/migrate/undo/validate/clean subcommand-specific options.

    ``--target-version`` is added per-command (rather than via a shared
    parent parser) because each command has a meaningfully different
    help string for the same flag — bugbot review on PR-09 flagged that
    a shared parent loses this user-facing context. The shared
    declaration would save 3 lines but degrade ``--help`` output.
    """
    migrate_parser.add_argument("--target-version", help="Target version to migrate to")
    undo_parser.add_argument("--target-version", help="Target version to roll back to")
    validate_parser.add_argument("--target-version", help="Validate migrations up to this version")
    # Validate specific options
    validate_parser.add_argument(
        "--skip-validation", action="store_true", help="Skip validation checks"
    )
    # Migrate specific options
    migrate_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate migrations without applying them",
    )
    migrate_parser.add_argument(
        "--mark-as-executed",
        action="store_true",
        help="Mark migrations as executed without running them (for migration applied outside dblift)",
    )
    migrate_parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Show SQL statements in command output and reports",
    )
    undo_parser.add_argument(
        "--show-sql",
        action="store_true",
        help="Show SQL statements in command output and reports",
    )
    clean_parser.add_argument(
        "--clean-enabled",
        dest="clean_disabled",
        action="store_false",
        default=None,
        help="Allow destructive clean execution. Without this flag, clean is disabled by default.",
    )
    clean_parser.add_argument(
        "--clean-disabled",
        dest="clean_disabled",
        action="store_true",
        default=None,
        help="Disable destructive clean execution (default).",
    )


def _register_builtin_command_parsers(
    parser: argparse.ArgumentParser,
) -> list[argparse.ArgumentParser]:
    """Register first-party command parsers that remain in the OSS CLI."""
    subparser_actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparser_actions:
        return []
    registered: list[argparse.ArgumentParser] = []

    return registered


def create_parser(
    exit_on_error: bool = True, suppress_errors: bool = False
) -> argparse.ArgumentParser:
    """Create and configure the argument parser for DBLift CLI."""
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument("--db-url", dest="database_url", help="Database URL")
    db_parent.add_argument("--db-username", dest="database_username", help="Database username")
    db_parent.add_argument("--db-password", dest="database_password", help="Database password")
    db_parent.add_argument("--db-schema", dest="database_schema", help="Database schema")
    # Hidden copy for the root parser: flags are parsed globally but shown in
    # subcommand --help only.
    db_parent_hidden = argparse.ArgumentParser(add_help=False)
    db_parent_hidden.add_argument("--db-url", dest="database_url", help=argparse.SUPPRESS)
    db_parent_hidden.add_argument("--db-username", dest="database_username", help=argparse.SUPPRESS)
    db_parent_hidden.add_argument("--db-password", dest="database_password", help=argparse.SUPPRESS)
    db_parent_hidden.add_argument("--db-schema", dest="database_schema", help=argparse.SUPPRESS)
    parser_kwargs: Dict[str, Any] = {
        "description": "dblift: Database migration tool",
        "parents": [db_parent_hidden],
    }
    if not exit_on_error:
        parser_kwargs["exit_on_error"] = False
    parser = argparse.ArgumentParser(**parser_kwargs)
    if suppress_errors:

        def silent_error(message: str) -> None:
            pass

        parser.error = silent_error  # type: ignore[method-assign,assignment]
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument(
        "--scripts",
        action="append",
        dest="scripts_list",
        help=(
            "Path to migration scripts directory (can be specified multiple "
            "times). Subdirectories are scanned by default; set "
            "migrations.recursive=false in YAML or pass --no-recursive to opt out."
        ),
    )
    # Batch-5 BUG-02: allow CLI override of recursive scan for --scripts. A
    # ``None`` default means "defer to config"; explicit ``--recursive`` /
    # ``--no-recursive`` win over the config value and the hard-coded default.
    recursive_group = parser.add_mutually_exclusive_group()
    recursive_group.add_argument(
        "--recursive",
        dest="recursive_flag",
        action="store_const",
        const=True,
        default=None,
        help="Scan --scripts directory recursively (default; overrides config).",
    )
    recursive_group.add_argument(
        "--no-recursive",
        dest="recursive_flag",
        action="store_const",
        const=False,
        help=(
            "Do not scan --scripts subdirectories (overrides config). "
            "Equivalent to migrations.recursive=false in YAML."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--log-dir", default="logs", help="Log directory")
    parser.add_argument("--log-format", default="text", help="Log format (text, json, html)")
    parser.add_argument(
        "--log-level",
        default="info",
        type=str.lower,
        choices=["debug", "info", "warn", "error"],
        help="Log level (case-insensitive)",
    )
    parser.add_argument("--log-file", help="Log file name")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help=(
            "Suppress info/debug log lines on console; success "
            "(NOTICE), warnings, and errors still shown. File/JSON/HTML "
            "logs are unaffected."
        ),
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable Rich progress bars and status spinners (useful in CI logs).",
    )
    subparsers = parser.add_subparsers(dest="command", required=False)
    # Shared subparser parents — each declares a cohesive cluster of args
    # that several subcommands inherit via ``parents=[...]``. Defining
    # each option exactly once here eliminates the ``for subparser in [...]``
    # loops that used to imperatively add them, and makes the inheritance
    # visible to argparse (so no subparser can accidentally redefine one
    # of these dests — structurally enforced by
    # ``tests/unit/cli/test_parser_invariants.py``).
    _history = _make_history_table_parent()
    _snapshot_table = _make_snapshot_table_parent()
    _strict = _make_strict_parent()
    _filter = _make_filter_parent()
    # Create all subcommand parsers
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Apply migrations",
        parents=[_history, _snapshot_table, _strict, _filter],
    )
    info_parser = subparsers.add_parser(
        "info",
        help="Show migration information",
        parents=[_history, _strict, _filter],
    )
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate migration scripts",
        parents=[_history, _strict, _filter],
    )
    undo_parser = subparsers.add_parser(
        "undo",
        help="Rollback migrations",
        parents=[_history, _snapshot_table, _strict, _filter],
    )
    clean_parser = subparsers.add_parser(
        "clean",
        help="Clean database schema (requires --clean-enabled or clean_disabled: false)",
        parents=[_history, _strict],
    )
    baseline_parser = subparsers.add_parser(
        "baseline",
        help="Baseline an existing database",
        parents=[_history, _snapshot_table],
    )
    repair_parser = subparsers.add_parser(
        "repair",
        help="Repair the schema history table",
        parents=[_history, _strict],
    )
    import_flyway_parser = subparsers.add_parser(
        "import-flyway",
        help="Import Flyway schema history",
        parents=[_history],  # import-flyway intentionally does not expose --strict
    )
    import_flyway_parser.add_argument(
        "--flyway-table",
        default="flyway_schema_history",
        help="Source Flyway schema history table name (default: flyway_schema_history)",
    )
    builtin_extension_parsers = _register_builtin_command_parsers(parser)
    # Configure arguments via extracted functions
    _add_baseline_options(baseline_parser)
    _add_diff_and_target_options(migrate_parser, undo_parser, validate_parser, clean_parser)
    # info --format option (JSON output for scripting)
    info_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )
    # DB utility commands
    db_parser = subparsers.add_parser("db", help="Database utility commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    setup_db_utils_parser(db_subparsers)
    load_command_extensions(parser)
    if suppress_errors:
        all_subparsers = [
            migrate_parser,
            info_parser,
            validate_parser,
            undo_parser,
            clean_parser,
            baseline_parser,
            repair_parser,
            import_flyway_parser,
            db_parser,
            *builtin_extension_parsers,
        ]

        def silent_error(message: str) -> None:
            pass

        for subparser in all_subparsers:
            subparser.error = silent_error  # type: ignore[method-assign,assignment]

        # Also suppress errors on extension parsers added by load_command_extensions
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(action.choices, dict):
                for choice_parser in action.choices.values():
                    if choice_parser not in all_subparsers:
                        choice_parser.error = silent_error

    return parser
