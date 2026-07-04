"""Configuration loading and setup helpers for dblift CLI."""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from api._cli_support import ConnectionProvider
from cli._parser_setup import create_parser, parse_with_selective_errors
from config.config_builder import ConfigBuilder
from config.dblift_config import _placeholder_tokens, load_config
from config.errors import ConfigurationError
from config.secrets._provider_base import SecretsResolutionError
from core.logger import LogFactory, LogFormat, LogLevel
from core.utils.database_url_parser import DatabaseUrlParser
from core.utils.string_utils import safe_split_first
from core.utils.url_masking import mask_database_url

# Global flags that are boolean (action="store_true") and therefore do NOT
# consume a following value. Without this set, `dblift --dry-run migrate`
# would treat `migrate` as --dry-run's value and leave `commands` empty.
_GLOBAL_BOOLEAN_FLAGS = frozenset(
    {
        "--version",
        "--dry-run",
        "--recursive",
        "--no-recursive",
        "--quiet",
        "-q",
        "--no-progress",
    }
)
_SUBCOMMAND_BOOLEAN_FLAGS = frozenset(
    {
        "--clean-disabled",
        "--clean-enabled",
        "--dry-run",
        "--generate-sql",
        "--ignore-unmanaged",
        "--include-drops",
        "--keep-container",
        "--managed-only",
        "--mark-as-executed",
        "--no-performance",
        "--show-sql",
        "--rehearse-rollback",
        "--skip-replay",
        "--skip-validation",
        "--skip-validate-sql",
        "--split-by-type",
        "--strict",
        "--unmanaged-only",
        "--validate-only",
    }
)


def _command_handler_attr(command: Optional[str], attr_name: str, default: Any = None) -> Any:
    if not command:
        return default
    from cli._command_handlers import _COMMAND_HANDLERS

    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        return default
    return getattr(handler, attr_name, default)


def _extract_commands_from_argv(
    argv_list: List[str],
    available_commands: List[str],
    global_only_args: List[str],
) -> Tuple[List[str], List[str], List[str]]:
    """Extract commands, global arguments, and subcommand arguments from argv.

    Returns:
        Tuple of (commands, global_arguments, subcommand_args)
    """
    commands = []
    global_arguments = []
    subcommand_args = []
    i = 0
    expecting_value_for = None
    stop_command_extraction = False

    while i < len(argv_list):
        arg = argv_list[i]

        if expecting_value_for:
            subcommand_args.append(arg)
            expecting_value_for = None
            i += 1
            continue

        if not stop_command_extraction and not arg.startswith("-") and arg in available_commands:
            commands.append(arg)
            i += 1
            # Commands with subcommands: stop extracting further commands,
            # but continue loop so global args are still extracted
            if arg in ("db", "license", "data"):
                stop_command_extraction = True
            continue

        arg_name = safe_split_first(arg, "=", default=arg)
        is_global_only = arg_name in global_only_args
        is_boolean_flag = arg_name in _GLOBAL_BOOLEAN_FLAGS

        if is_global_only:
            global_arguments.append(arg)
            # Boolean store_true flags (--dry-run, --version) never consume the
            # next token. Args with inline value (--config=foo) also already
            # carry their value, so skip the lookahead — otherwise the next
            # token (often a command name) gets swallowed into globals.
            has_inline_value = "=" in arg
            if (
                not is_boolean_flag
                and not has_inline_value
                and i + 1 < len(argv_list)
                and not argv_list[i + 1].startswith("-")
            ):
                global_arguments.append(argv_list[i + 1])
                i += 2
            else:
                i += 1
        else:
            subcommand_args.append(arg)
            if arg.startswith("--") and arg_name not in _SUBCOMMAND_BOOLEAN_FLAGS:
                has_inline_value = "=" in arg
                if (
                    not has_inline_value
                    and i + 1 < len(argv_list)
                    and not argv_list[i + 1].startswith("-")
                ):
                    expecting_value_for = arg
                else:
                    expecting_value_for = None
            i += 1

    return commands, global_arguments, subcommand_args


def _build_args_namespace(
    commands: List[str], global_arguments: List[str], subcommand_args: List[str]
) -> Tuple[argparse.Namespace, List[str]]:
    """Parse arguments using argparse for single or multi-command mode.

    Returns:
        Tuple of (args, unknown_args)
    """
    original_argv = sys.argv.copy()

    if commands:
        sys.argv = [sys.argv[0]] + global_arguments + [commands[0]] + subcommand_args

    if len(commands) > 1:
        parser = create_parser(exit_on_error=False, suppress_errors=True)
        args, unknown_args, has_validation_error = parse_with_selective_errors(parser)
        if has_validation_error:
            # argparse convention: exit 2 on usage/validation errors so scripts can detect
            # them with `$?` (BUG-05).
            sys.exit(2)

        if args is None:
            args = argparse.Namespace()
            unknown_args = subcommand_args
            args.command = commands[0] if commands else None
            args.config = None
            args.scripts_list = None
            args.dry_run = False
            args.log_dir = "logs"
            args.log_format = "text"
            args.log_level = "info"
            args.log_file = None
            args.database_url = None
            args.database_username = None
            args.database_password = None
            args.database_schema = None

        def extract_db_arg(attr_name: str, cli_arg: str) -> None:
            """Extract database connection argument from global_arguments."""
            if not hasattr(args, attr_name) or getattr(args, attr_name) is None:
                setattr(args, attr_name, None)
                for arg in global_arguments:
                    if arg.startswith(f"{cli_arg}="):
                        setattr(args, attr_name, arg.split("=", 1)[1])
                        return
                for i, arg in enumerate(global_arguments):
                    if arg == cli_arg and i + 1 < len(global_arguments):
                        setattr(args, attr_name, global_arguments[i + 1])
                        return

        if not hasattr(args, "command") or args.command is None:
            args.command = commands[0] if commands else None
        if not hasattr(args, "config"):
            args.config = None
        if not hasattr(args, "scripts_list"):
            args.scripts_list = None
        if not hasattr(args, "dry_run"):
            args.dry_run = False

        extract_db_arg("database_url", "--db-url")
        extract_db_arg("database_username", "--db-username")
        extract_db_arg("database_password", "--db-password")
        extract_db_arg("database_schema", "--db-schema")
    else:
        parser = create_parser()
        args = parser.parse_args()
        unknown_args = []

    sys.argv = original_argv
    return args, unknown_args


# Default config filenames searched in the current working directory when no
# --config is given, in precedence order. Lets `dblift <command>` run without an
# explicit --config when a config file sits in the project root, matching the
# convention of peer tools (Alembic's alembic.ini, Flyway's flyway.conf).
_DEFAULT_CONFIG_NAMES: Tuple[str, ...] = ("dblift.yaml", "dblift.yml")


def _discover_default_config(log: Any = None) -> Optional[str]:
    """Return the path to a default config file in the cwd, or None.

    Searches the current working directory for the filenames in
    :data:`_DEFAULT_CONFIG_NAMES` and returns the first match. Returns ``None``
    when no default config is present, preserving the existing behaviour for
    pure ``--db-url`` workflows.
    """
    cwd = Path.cwd()
    for name in _DEFAULT_CONFIG_NAMES:
        candidate = cwd / name
        if candidate.is_file():
            if log:
                log.debug(f"Using discovered config file: {candidate}")
            return str(candidate)
    return None


def _load_and_merge_config(args: argparse.Namespace, log: Any) -> Any:
    """Load configuration and merge database overrides from CLI arguments.

    Returns:
        Loaded and merged config object
    """
    # Auto-discover a config file in the cwd when the user passed neither
    # --config nor --db-url, so `dblift <command>` works from a project that has
    # a dblift.yaml without forcing an explicit --config on every invocation.
    if not getattr(args, "config", None) and not getattr(args, "database_url", None):
        discovered = _discover_default_config(log)
        if discovered:
            args.config = discovered

    try:
        config = load_config(args.config, args)
    except (
        ConfigurationError,
        FileNotFoundError,
        RuntimeError,
        ValueError,
        SecretsResolutionError,
    ) as e:
        message = str(e)
        if isinstance(e, ConfigurationError) and (
            "No configuration source provided" in message
            or "Database configuration is required" in message
        ):
            message = "Database URL is required"
        print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    db_overrides = {}
    if hasattr(args, "database_url") and args.database_url:
        db_overrides["url"] = args.database_url
    if hasattr(args, "database_username") and args.database_username:
        db_overrides["username"] = args.database_username
    if hasattr(args, "database_password") and args.database_password:
        db_overrides["password"] = args.database_password
    if hasattr(args, "database_schema") and args.database_schema:
        db_overrides["schema"] = args.database_schema

    if db_overrides:
        command = getattr(args, "command", None)
        commands_list = getattr(args, "commands_list", None) or ([command] if command else [])
        is_offline = len(commands_list) == 1 and bool(
            _command_handler_attr(command, "_dblift_skip_secret_resolution", False)
        )
        if not is_offline:
            from config.secrets._resolver import resolve_secret_refs

            try:
                db_overrides = resolve_secret_refs({"database": db_overrides}, config.secrets).get(
                    "database", db_overrides
                )
            except SecretsResolutionError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        config.database = ConfigBuilder.merge_database_overrides(config.database, db_overrides)

    if log:
        log.debug(f"Database config type: {type(config.database).__name__}")
        log.debug(f"Database server: {getattr(config.database, 'server', 'Not set')}")
        log.debug(f"Database name: {getattr(config.database, 'database_name', 'Not set')}")
        raw_url = getattr(config.database, "url", "Not set")
        masked_url = (
            mask_database_url(str(raw_url)) if raw_url and raw_url != "Not set" else raw_url
        )
        log.debug(f"Database URL: {masked_url}")

    if hasattr(args, "table_name") and args.table_name:
        config.history_table = args.table_name

    if hasattr(args, "snapshot_table") and args.snapshot_table:
        config.snapshot_table = args.snapshot_table

    if hasattr(args, "installed_by") and args.installed_by:
        config.database.installed_by = args.installed_by
    elif not getattr(config.database, "installed_by", None) and getattr(
        config.database, "username", None
    ):
        config.database.installed_by = config.database.username

    return config


def _validate_log_format_for_cli(args: Any, parser: Any) -> None:
    """Validate ``--log-format`` before config load. Calls ``parser.error()`` on failure."""
    valid_formats = ["text", "json", "html"]
    raw = getattr(args, "log_format", None) or "text"
    for fmt in str(raw).split(","):
        if fmt.strip().lower() not in valid_formats:
            parser.error(
                f"Invalid log format: {fmt.strip()}. Valid formats are: {', '.join(valid_formats)}"
            )


def _validate_db_config(
    args: argparse.Namespace,
    config: Any,
    parser: argparse.ArgumentParser,
    commands: List[str],
) -> None:
    """Validate database configuration for migration commands.

    Calls parser.error() (raises SystemExit) if validation fails.
    """
    # db utility commands exit before _configure_logging — skip database checks here
    # (``--log-format`` is validated earlier via :func:`_validate_log_format_for_cli`).
    if commands and commands[0] == "db":
        return

    migration_commands = {
        "migrate",
        "undo",
        "clean",
        "validate",
        "info",
        "repair",
        "import-flyway",
        "baseline",
    }
    if _command_handler_attr(args.command, "_dblift_validate_db_config", False):
        migration_commands.add(args.command)
    if args.command not in migration_commands:
        return

    db_type = (
        getattr(config.database, "type", "").lower()
        if hasattr(config, "database") and config.database
        else ""
    )

    from api._cli_support import ProviderRegistry

    _qcs = ProviderRegistry.get_quirks((db_type or "").lower())
    if _qcs.url_optional_when_file_path_given:
        if not hasattr(config, "database") or not config.database:
            parser.error(
                f"Database configuration is required for '{db_type}'. "
                "Specify it in the config file or environment variables."
            )
        path = getattr(config.database, "path", None)
        database = getattr(config.database, "database", None)
        url = getattr(config.database, "url", None)
        if not path and not database and not url:
            parser.error(
                f"Database path is required for '{db_type}'. "
                "Specify it in the config file (path, database, or url field), "
                "environment variables, or command line."
            )
        if not getattr(config.database, "schema", None) and _qcs.default_schema_name:
            config.database.schema = _qcs.default_schema_name
    elif not _qcs.requires_credentials:
        # CosmosDB and similar: no URL validation needed.
        pass
    else:
        if not hasattr(config, "database") or not config.database:
            parser.error(
                "Database configuration is required. Specify it in the config file or environment variables."
            )

        url_provided = hasattr(args, "database_url") and getattr(args, "database_url", None)
        url_exists = getattr(config.database, "url", None)
        has_connection_identifier = _qcs.has_connection_identifier(config.database)

        if not url_provided and not url_exists and not has_connection_identifier:
            parser.error(_qcs.missing_connection_identifier_hint)

        url_username = DatabaseUrlParser.parse_username(config.database.url) if url_exists else None
        url_password = DatabaseUrlParser.parse_password(config.database.url) if url_exists else None

        if not getattr(config.database, "username", None) and not url_username:
            parser.error(
                "Database username is required. Specify it in the config file, environment variables, or command line."
            )

        if not getattr(config.database, "password", None) and not url_password:
            parser.error(
                "Database password is required. Specify it in the config file, environment variables, or command line."
            )

        if not getattr(config.database, "schema", None):
            derived_schema = _qcs.derive_schema_name(config.database)
            if derived_schema:
                config.database.schema = derived_schema

        if _qcs.schema_required and not getattr(config.database, "schema", None):
            parser.error(
                "Database schema is required. Specify it in the config file, environment variables, or command line."
            )

    # For baseline command, default to version "1" if not specified
    if args.command == "baseline" and not getattr(args, "baseline_version", None):
        args.baseline_version = "1"


def _configure_logging(
    args: argparse.Namespace, config: Any, parser: argparse.ArgumentParser
) -> Any:
    """Configure logging system and return configured logger.

    Returns:
        Configured log instance
    """
    log_dir_path = Path(args.log_dir if args.log_dir is not None else "logs")
    log_dir_path.mkdir(parents=True, exist_ok=True)

    _LOG_LEVEL_MAP = {
        "debug": LogLevel.DEBUG,
        "warn": LogLevel.WARN,
        "error": LogLevel.ERROR,
    }
    log_level = _LOG_LEVEL_MAP.get(args.log_level, LogLevel.INFO)
    # ``--quiet`` raises the *console* threshold to NOTICE so info/debug
    # lines disappear from the terminal while NOTICE (success
    # confirmations, "Command completed"), WARN, and ERROR still show
    # — matching the help text. NOTICE has priority 25 (between INFO=20
    # and WARN=30) so a WARN threshold would silently swallow success
    # messages that operators using --quiet still expect to see.
    # File / JSON / HTML logs keep ``log_level`` so the audit trail stays
    # complete (the file sinks are the record of what happened —
    # silencing them would hide migration steps from post-mortems).
    console_log_level: Optional[LogLevel] = None
    if getattr(args, "quiet", False) and log_level not in (
        LogLevel.NOTICE,
        LogLevel.WARN,
        LogLevel.ERROR,
    ):
        console_log_level = LogLevel.NOTICE
    if getattr(args, "no_progress", False):
        from core.logger.console import set_progress_disabled

        set_progress_disabled(True)

    format_strings = [f.strip().lower() for f in args.log_format.split(",")]

    _LOG_FORMAT_MAP = {
        "html": LogFormat.HTML,
        "json": LogFormat.JSON,
        "text": LogFormat.TEXT,
    }
    primary_log_format = _LOG_FORMAT_MAP.get(
        format_strings[0] if format_strings else "", LogFormat.TEXT
    )

    url = config.database.url
    db_name = DatabaseUrlParser.parse_database_name(url)

    if not db_name:
        raw_path = getattr(config.database, "path", None)
        db_name = (
            getattr(config.database, "database_name", None)
            or getattr(config.database, "server", None)
            or getattr(config.database, "service_name", None)
            or getattr(config.database, "sid", None)
            or (Path(raw_path).stem if raw_path else None)
        )

    if hasattr(config.database, "database_name"):
        config.database.database_name = db_name

    additional_formats = [
        _LOG_FORMAT_MAP[fmt] for fmt in format_strings[1:] if fmt in _LOG_FORMAT_MAP
    ]

    LogFactory.configure(
        log_dir=log_dir_path,
        log_format=primary_log_format,
        schema=config.database.schema,
        database_name=db_name,
        log_file_pattern=args.log_file,
        log_level=log_level,
        additional_formats=additional_formats,
        console_log_level=console_log_level,
    )

    log = LogFactory.get_log("Dblift")
    log.debug(f"Using database name: {db_name}")
    return log


def _resolve_scripts_directories(
    args: argparse.Namespace,
    config: Any,
    parser: argparse.ArgumentParser,
    commands: List[str],
) -> Tuple[Optional[Path], List[Path], bool, Dict[Path, bool]]:
    """Resolve migration scripts directories from CLI args or config.

    Returns:
        Tuple of (scripts_dir, additional_scripts_dirs, recursive, dir_recursive_map)
    """
    scripts_dir = None
    additional_scripts_dirs = []
    dir_recursive_map = {}

    # Determine base directory for resolving relative paths.
    # If a config file was specified, resolve relative to its parent directory;
    # otherwise fall back to CWD.
    config_base_dir = Path.cwd()
    if hasattr(args, "config") and args.config:
        config_path = Path(args.config)
        if config_path.exists():
            config_base_dir = config_path.resolve().parent

    if hasattr(args, "scripts_list") and args.scripts_list:
        scripts_dir = Path(args.scripts_list[0]).resolve()
        if not scripts_dir.exists() and args.command not in ["baseline"]:
            parser.error(f"Migration scripts directory not found: {args.scripts_list[0]}")

        config.migrations.directory = str(scripts_dir)

        if len(args.scripts_list) > 1:
            for scripts_path in args.scripts_list[1:]:
                add_dir = Path(scripts_path).resolve()
                if not add_dir.exists():
                    parser.error(f"Additional scripts directory not found: {scripts_path}")
                additional_scripts_dirs.append(add_dir)

        recursive = getattr(config.migrations, "recursive", True)
    else:
        dir_configs = config.migrations.get_directory_configs()

        if dir_configs:
            scripts_dir = Path(dir_configs[0].path)
            # Resolve relative paths against config file directory
            if not scripts_dir.is_absolute():
                scripts_dir = config_base_dir / scripts_dir
            if len(dir_configs) > 1:
                for dir_config in dir_configs[1:]:
                    add_dir = Path(dir_config.path)
                    if not add_dir.is_absolute():
                        add_dir = config_base_dir / add_dir
                    additional_scripts_dirs.append(add_dir)
                    if not dir_config.recursive:
                        dir_recursive_map[add_dir] = False

            if not dir_configs[0].recursive:
                dir_recursive_map[scripts_dir] = False

            recursive = dir_configs[0].recursive
        else:
            scripts_dir = config_base_dir / "migrations"
            recursive = getattr(config.migrations, "recursive", True)

    # Batch-5 BUG-02: CLI --recursive / --no-recursive wins over config and
    # default. ``recursive_flag`` is ``None`` when neither is passed, so the
    # branches above remain authoritative unless the user explicitly asked.
    cli_recursive = getattr(args, "recursive_flag", None)
    if cli_recursive is not None:
        recursive = cli_recursive
        if hasattr(config, "migrations") and hasattr(config.migrations, "recursive"):
            config.migrations.recursive = cli_recursive
        if scripts_dir is not None:
            dir_recursive_map[scripts_dir] = cli_recursive
        for add_dir in additional_scripts_dirs:
            dir_recursive_map[add_dir] = cli_recursive

    return scripts_dir, additional_scripts_dirs, recursive, dir_recursive_map


def _collect_placeholders(args: argparse.Namespace, config: Any) -> Dict[str, Any]:
    """Collect SQL placeholders from config and CLI arguments.

    Returns:
        Dict of placeholder key-value pairs
    """
    placeholders = {}

    if hasattr(config, "placeholders") and config.placeholders:
        placeholders.update(config.placeholders)

    for placeholder in _placeholder_tokens(getattr(args, "placeholders", None)):
        if "=" in placeholder:
            key, value = placeholder.split("=", 1)
            placeholders[key.strip()] = value.strip()

    return placeholders


def _close_logs(log: Any) -> None:
    """Ensure all log handlers are properly closed."""
    if hasattr(log, "close"):
        log.close()
    elif hasattr(log, "logs"):
        for logger in log.logs:
            if hasattr(logger, "close"):
                logger.close()


def _ensure_connection(client: Any, log: Any, command: str) -> None:
    """Ensure database connection is active before a command."""
    if not client or not hasattr(client, "provider"):
        return
    try:
        connection_needed = True
        is_connection_provider = isinstance(client.provider, ConnectionProvider)
        if is_connection_provider:
            try:
                if client.provider.is_connected():
                    connection_needed = False
                    log.debug(f"Connection already active before command {command}")
            except Exception as e:
                log.debug(f"Could not check connection state before command {command}: {e}")
        if connection_needed:
            if hasattr(client.provider, "ensure_connection"):
                client.provider.ensure_connection()
                log.debug(f"Ensured connection active before command {command}")
            elif is_connection_provider:
                client.provider.create_connection()
                log.debug(f"Created new connection before command {command}")
    except Exception as e:
        log.debug(f"Connection check before command {command}: {e}")
