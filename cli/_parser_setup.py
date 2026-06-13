"""Parser setup functions for the dblift CLI.

Extracted from cli/main.py (story 20-16) to reduce file size.
Contains the 7 argparse configuration functions.
"""

import argparse
import io
import sys
from typing import Any, Dict, List, Optional, Tuple

from cli._constants import FAIL_ON_CHOICES, VALIDATE_SQL_FORMATS
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


def _setup_export_schema_options(
    export_schema_parser: argparse.ArgumentParser,
    snapshot_parser: argparse.ArgumentParser | None = None,
) -> None:
    """Configure all arguments for export-schema and, optionally, snapshot."""
    # Export schema output options
    export_schema_parser.add_argument(
        "--output",
        help="Output file path (single file output). Use --output-dir for directory output",
    )
    export_schema_parser.add_argument(
        "--output-dir",
        help="Output directory path (for split-by-type output or multiple files)",
    )
    export_schema_parser.add_argument(
        "--source",
        # BUG-04: accept ``database-stored`` as a deprecated alias of
        # ``database-model`` so ``snapshot --source`` and
        # ``export-schema --source`` share vocabulary. Normalized in
        # ``_handle_export_schema``.
        choices=["database-model", "database-stored", "file-model", "live-database"],
        default="live-database",
        help="Source for schema data: 'database-model' (latest snapshot from database), "
        "'file-model' (JSON model file), or 'live-database' (default, introspect live database). "
        "'database-stored' is accepted as a deprecated alias for 'database-model'.",
    )
    export_schema_parser.add_argument(
        "--snapshot-model",
        help="Path to JSON model file (required when --source=file-model)",
    )
    export_schema_parser.add_argument(
        "--split-by-type",
        action="store_true",
        help="Split output into separate files by object type (requires --output-dir)",
    )
    export_schema_parser.add_argument(
        "--description",
        help="Description to include in migration header",
    )
    if snapshot_parser is not None:
        _setup_snapshot_options(snapshot_parser)
    # Export schema filtering options
    export_schema_parser.add_argument(
        "--schema",
        help="Database schema name to export (default: use config schema). Only objects from this schema will be exported.",
    )
    export_schema_parser.add_argument(
        "--tables",
        help="Comma-separated list of table names to export (filters to specific tables and related objects)",
    )
    export_schema_parser.add_argument(
        "--types",
        help="Comma-separated list of object types to export (e.g., tables,views,indexes,functions,triggers)",
    )
    export_schema_parser.add_argument(
        "--managed-only",
        action="store_true",
        help="Export only objects defined in applied migrations (tracked objects). "
        "Requires --scripts directory to parse migration files.",
    )
    export_schema_parser.add_argument(
        "--unmanaged-only",
        action="store_true",
        help="Export only objects not defined in applied migrations (brownfield baseline). "
        "Requires --scripts directory to parse migration files.",
    )
    export_schema_parser.add_argument(
        "--include-drops",
        action="store_true",
        help="Include DROP statements in output (for clean recreation)",
    )
    # Export-schema specific migration filtering options
    export_schema_parser.add_argument(
        "--tags",
        help="Only consider migrations with specified tags when determining managed objects (comma-separated list)",
    )
    export_schema_parser.add_argument(
        "--exclude-tags",
        help="Exclude migrations with specified tags when determining managed objects (comma-separated list)",
    )
    export_schema_parser.add_argument(
        "--versions",
        help="Only consider specific migration versions when determining managed objects (comma-separated list)",
    )
    export_schema_parser.add_argument(
        "--exclude-versions",
        help="Exclude specific migration versions when determining managed objects (comma-separated list)",
    )
    # Export-schema target version
    export_schema_parser.add_argument(
        "--target-version",
        help="Only consider migrations up to this version when determining managed objects",
    )


def _setup_snapshot_options(snapshot_parser: argparse.ArgumentParser) -> None:
    """Configure snapshot command arguments for extension registration."""
    snapshot_parser.add_argument(
        "--output",
        required=True,
        help="Output file path for the snapshot JSON model",
    )
    snapshot_parser.add_argument(
        "--source",
        choices=["database-stored", "live-database"],
        default="database-stored",
        help="Source for snapshot data: 'database-stored' (default) loads latest from database, "
        "'live-database' captures new snapshot from live database introspection",
    )
    # B8-BUG-05: allow callers to accept snapshots below the default HIGH
    # confidence threshold. Emulators (CosmosDB, SQL Server dev, etc.)
    # routinely score MEDIUM/LOW because metadata views are incomplete; this
    # flag lets a user say "I accept 0.4 confidence for the emulator".
    # Value is the minimum overall_score in [0.0, 1.0] required to succeed.
    snapshot_parser.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        metavar="SCORE",
        help="Minimum acceptable snapshot confidence score (0.0-1.0). "
        "When a live-database snapshot scores below SCORE the command fails. "
        "Useful to bypass HIGH-only gating against emulators (e.g. --min-confidence 0.4).",
    )


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


def _setup_diff_options(diff_parser: argparse.ArgumentParser) -> None:
    """Configure arguments specific to the diff/drift command."""
    diff_parser.add_argument("--target-version", help="Compare migrations up to this version")
    diff_parser.add_argument(
        "--ignore-unmanaged",
        action="store_true",
        help="Hide unmanaged objects section (objects not in migrations)",
    )
    diff_parser.add_argument(
        "--snapshot-model",
        dest="snapshot_model",
        help="Path to a schema snapshot model file (JSON or encoded) to compare against",
    )
    diff_parser.add_argument(
        "--generate-sql",
        action="store_true",
        help="Generate SQL script to synchronize schemas based on detected differences",
    )
    diff_parser.add_argument(
        "--output-file",
        help="Output file path for generated SQL script (requires --generate-sql)",
    )


def _add_diff_and_target_options(
    diff_parser: argparse.ArgumentParser | None,
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
    if diff_parser is not None:
        _setup_diff_options(diff_parser)
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


def _add_validate_sql_options(validate_sql_parser: argparse.ArgumentParser) -> None:
    """Configure arguments specific to the validate-sql command."""
    validate_sql_parser.add_argument(
        "files",
        nargs="*",
        help="SQL files or directories to validate (defaults to migration scripts directory)",
    )
    validate_sql_parser.add_argument(
        "--dialect",
        # lint: allow-dialect-string: dialect dispatch
        choices=["oracle", "postgresql", "mysql", "sqlserver", "db2", "sqlite"],
        help="SQL dialect (defaults to dialect from database config)",
    )
    validate_sql_parser.add_argument(
        "--format",
        choices=list(VALIDATE_SQL_FORMATS),
        help="Output format (default: console)",
    )
    validate_sql_parser.add_argument(
        "--output",
        help="Optional file path for console, JSON, SARIF, GitLab, compact, or HTML output",
    )
    validate_sql_parser.add_argument(
        "--fail-on",
        choices=list(FAIL_ON_CHOICES),
        default=None,
        help="Minimum finding severity that makes the command fail (default: from config or error)",
    )
    validate_sql_parser.add_argument(
        "--severity-threshold",
        choices=["error", "warning", "info"],
        help="Minimum severity to report (default: from config or 'warning')",
    )
    validate_sql_parser.add_argument(
        "--rules-file", help="Path to custom validation rules YAML file"
    )
    validate_sql_parser.add_argument(
        "--profile",
        dest="rule_profile",
        help=("Built-in validation profile to apply " "(core, enterprise, strict, technical-debt)"),
    )
    validate_sql_parser.add_argument(
        "--rules",
        action="append",
        help=(
            "Rule packs or individual rules to apply; accepts comma-separated " "or repeated values"
        ),
    )
    validate_sql_parser.add_argument(
        "--no-performance",
        action="store_true",
        help="Disable performance analysis (only run business rules)",
    )


def _add_plan_options(plan_parser: argparse.ArgumentParser) -> None:
    plan_parser.add_argument(
        "--snapshot-model",
        required=True,
        help="Path to the DBLift snapshot model representing the target environment state",
    )
    plan_parser.add_argument(
        "--skip-validate-sql",
        action="store_true",
        help="Do not run SQL validation on planned migration scripts",
    )
    plan_parser.add_argument(
        "--validate-scope",
        choices=["pending", "all"],
        default="pending",
        help="SQL validation scope (default: pending)",
    )
    plan_parser.add_argument(
        "--format",
        default="text",
        metavar="FORMAT[,FORMAT...]",
        help=(
            "Report format(s): text, json, html, sarif, github-actions, gitlab, compact; "
            "comma-separate values to write multiple artifacts"
        ),
    )
    plan_parser.add_argument(
        "--fail-on",
        choices=list(FAIL_ON_CHOICES),
        default="error",
        help="Minimum finding severity that makes the command fail (default: error)",
    )
    plan_parser.add_argument(
        "--output", help="Optional file path for text, JSON, or HTML plan output"
    )
    plan_parser.add_argument(
        "--output-dir",
        help="Directory for timestamped report artifacts when multiple formats are requested",
    )


def _add_preflight_options(preflight_parser: argparse.ArgumentParser) -> None:
    preflight_parser.add_argument(
        "--snapshot-model",
        required=True,
        help="Path to the DBLift snapshot model representing the target environment state",
    )
    container_mode = preflight_parser.add_mutually_exclusive_group(required=True)
    container_mode.add_argument(
        "--container-image", help="Docker image to start for migration replay"
    )
    container_mode.add_argument(
        "--container-existing",
        help="Name or ID of an already-running validation database container",
    )
    container_mode.add_argument(
        "--skip-replay",
        action="store_true",
        help="Run plan and SQL validation without replaying migrations in a container",
    )
    preflight_parser.add_argument("--container-name", help="Name for the managed Docker container")
    preflight_parser.add_argument(
        "--container-env",
        action="append",
        default=[],
        help="Environment variable for managed Docker container, KEY=VALUE; repeatable",
    )
    preflight_parser.add_argument(
        "--container-env-file",
        dest="container_env_file",
        metavar="PATH",
        help="File of env vars to pass to the validation container (docker --env-file)",
    )
    preflight_parser.add_argument(
        "--container-port",
        action="append",
        default=[],
        help="Port mapping for managed Docker container, HOST:CONTAINER; repeatable",
    )
    preflight_parser.add_argument(
        "--container-wait-timeout",
        type=int,
        default=120,
        help="Seconds to wait for the validation database to become usable",
    )
    preflight_parser.add_argument(
        "--replay-scope",
        choices=["all", "planned"],
        default="all",
        help=(
            "Migration replay scope: all for empty containers, planned for containers "
            "preloaded with history matching the snapshot (default: all)"
        ),
    )
    preflight_parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Do not remove a managed validation container after preflight",
    )
    preflight_parser.add_argument(
        "--format",
        default="text",
        metavar="FORMAT[,FORMAT...]",
        help=(
            "Report format(s): text, json, html, sarif, github-actions, gitlab, compact; "
            "comma-separate values to write multiple artifacts"
        ),
    )
    preflight_parser.add_argument(
        "--fail-on",
        choices=list(FAIL_ON_CHOICES),
        default="error",
        help="Minimum finding severity that makes the command fail (default: error)",
    )
    preflight_parser.add_argument(
        "--output",
        help="Optional file path for text, JSON, or HTML preflight output",
    )
    preflight_parser.add_argument(
        "--output-dir",
        help="Directory for timestamped report artifacts when multiple formats are requested",
    )
    preflight_parser.add_argument(
        "--rehearse-rollback",
        action="store_true",
        dest="rehearse_rollback",
        default=False,
        help="After replay, also run undo migrations to verify rollback scripts work",
    )



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
    builtin_extension_parsers: list = []
    # Configure arguments via extracted functions
    _add_baseline_options(baseline_parser)
    _add_diff_and_target_options(None, migrate_parser, undo_parser, validate_parser, clean_parser)
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
