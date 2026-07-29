"""CLI utilities for native database driver diagnostics."""

import argparse
import os
import pprint
import traceback
from pathlib import Path
from typing import Any, Dict, List

from api._cli_support import (
    ProviderRegistry,
    get_provider_display_url,
)
from cli._output import CommandOutput, from_args
from config.dblift_config import load_config
from core.logger import DbliftLogger, LogFormat
from core.utils.url_masking import mask_database_url
from db.error import format_connection_error


def _to_python(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_python(v) for v in obj]
    elif hasattr(obj, "__str__") and not isinstance(obj, (str, int, float, bool, type(None))):
        return str(obj)
    else:
        return obj


def list_drivers(args: argparse.Namespace) -> int:
    """List native Python drivers and their import status.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    out = from_args(args)
    try:
        # Get available drivers
        driver_status = ProviderRegistry.get_available_drivers()

        # Prepare output
        out.status("Native Driver Status:")
        out.status("=====================")

        # Calculate column width for nice output
        max_name_width = max(len(db_type) for db_type in driver_status.keys())
        format_str = f"  {{:{max_name_width}}}  : {{}}"

        # Print drivers and their status
        for db_type, is_available in sorted(driver_status.items()):
            status = "Available" if is_available else "Not available"
            out.status(format_str.format(db_type, status))

        if not all(driver_status.values()):
            out.status(
                "\nInstall missing drivers with the matching pip extra, e.g. dblift[postgresql]."
            )

        return 0
    except Exception as e:
        out.error(f"Error listing drivers: {str(e)}")
        return 1


def validate_config(args: argparse.Namespace) -> int:
    """Validate database configuration and driver availability.

    Args:
        args: Command line arguments including configuration

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    out = from_args(args)
    try:
        config_file = getattr(args, "config", None)
        if config_file:
            # If the user passed --config, load it: otherwise validate-config is useless as a
            # config-file linter, since DbliftConfig.from_args only reads CLI flags (BUG-02).
            try:
                config = load_config(config_file, args)
            except (FileNotFoundError, RuntimeError) as load_err:
                out.error(f"Error: {load_err}")
                return 1
        else:
            # Batch-6 BUG-04: without ``--config`` and without ``--db-url`` (or
            # the ``DBLIFT_DB_URL`` env var), ``load_config`` returns a config
            # populated from an implicit SQL Server placeholder. That can report
            # "valid" even though the user supplied nothing to validate.
            cli_url = getattr(args, "db_url", None) or getattr(args, "database_url", None)
            env_url = os.environ.get("DBLIFT_DB_URL") or os.environ.get("DBLIFT_DATABASE_URL")
            has_db_env = any(k.startswith("DBLIFT_DB_") for k in os.environ)
            if not cli_url and not env_url and not has_db_env:
                out.error(
                    "Error: no configuration source provided. Pass --config, "
                    "--db-url, or set DBLIFT_DB_* environment variables."
                )
                return 1
            config = load_config(None, args)

        # Validate the configuration
        is_valid, error_message = ProviderRegistry.validate_database_configuration(config)

        if is_valid:
            out.status("Database configuration and driver are valid.")
            # B9-NOTE-02: validate-config only checks URL/driver structure. For
            # server-based providers (postgres/mysql/oracle/sqlserver/db2), empty
            # credentials are a near-certain misconfiguration — warn explicitly
            # and point users at check-connection for live credential testing.
            _warn_if_missing_credentials(config, out)
            return 0
        else:
            out.error(f"Error: {error_message}")
            return 1
    except Exception as e:
        out.error(f"Error validating configuration: {str(e)}")
        return 1


_CREDENTIALLESS_TEST_TYPES = frozenset({"dummy"})


def _is_credentialless(db_type: str) -> bool:
    if db_type in _CREDENTIALLESS_TEST_TYPES:
        return True
    return not ProviderRegistry.get_quirks((db_type or "").lower()).requires_credentials


def _warn_if_missing_credentials(config: Any, out: CommandOutput) -> None:
    """Emit a stderr warning when required credentials are empty (B9-NOTE-02).

    ``validate-config`` historically reported "valid" even when
    ``username``/``password`` were absent because it only checks URL shape and
    driver availability. For providers that always need credentials, that
    silence is misleading. Emit a non-fatal warning so users notice before
    they hit a confusing auth failure at ``check-connection`` or ``migrate``.
    """
    database = getattr(config, "database", None)
    if database is None:
        return
    db_type = (getattr(database, "type", None) or "").lower()
    if not db_type or _is_credentialless(db_type):
        return
    username = getattr(database, "username", None)
    password = getattr(database, "password", None)
    missing = []
    if not username or not str(username).strip():
        missing.append("username")
    if not password or not str(password).strip():
        missing.append("password")
    if not missing:
        return
    fields = " and ".join(missing)
    out.error(
        f"Warning: {fields} not set for database type '{db_type}'. "
        f"validate-config checks configuration structure only; use "
        f"'db check-connection' to verify that credentials actually work."
    )


def diagnose_connection(args: argparse.Namespace) -> int:
    """Report native driver availability and plugin discovery details.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    out = from_args(args)
    try:
        fmt = getattr(args, "format", "text")
        plugins = ProviderRegistry.list_plugins()
        driver_diagnostics: Dict[str, bool] = ProviderRegistry.get_available_drivers()
        plugin_diagnostics: List[Dict[str, Any]] = [
            {
                "name": plugin.name,
                "dialects": plugin.dialects,
                "transport": plugin.transport,
                "native_driver_module": plugin.native_driver_module,
            }
            for plugin in plugins
        ]
        diagnostics: Dict[str, Any] = {
            "drivers": driver_diagnostics,
            "plugins": plugin_diagnostics,
        }

        # Output diagnostics in requested format
        if fmt == "json":
            out.machine(_to_python(diagnostics))
        elif fmt == "pretty":
            # Route via ``out`` so any custom stdout stream injected into
            # CommandOutput (tests, piping) is respected. Using
            # ``pprint.pformat`` keeps the same human-readable layout as
            # ``pprint.pprint``.
            out.status(pprint.pformat(diagnostics))
        else:  # Default text format
            # Print headers and sections in a more readable format
            out.status("\n=== NATIVE DRIVER DIAGNOSTICS ===\n")
            out.status("Drivers:")
            for db_type, available in sorted(driver_diagnostics.items()):
                out.status(f"  {db_type}: {'available' if available else 'missing'}")
            out.status("\nPlugins:")
            for plugin in plugin_diagnostics:
                module = plugin["native_driver_module"] or "built-in"
                out.status(f"  {plugin['name']}: {plugin['transport']} ({module})")

            out.status("\n=== END OF REPORT ===\n")

        return 0
    except Exception as e:
        out.error(f"Error performing native driver diagnostics: {e}")
        traceback.print_exc()
        return 1


def check_connection(args: argparse.Namespace) -> int:
    """Test database connection using provided parameters.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    out = from_args(args)
    try:
        results: Dict[str, Any] = {
            "success": False,
            "error": None,
            "connection_info": {},
            "database_info": {},
        }

        # Initialize logger — honour --log-dir, --log-format, and --log-file.
        # db subcommands run before the main _configure_logging call so we
        # replicate the relevant subset here. ``log_file_pattern`` accepts an
        # absolute path (Path division replaces ``log_dir``) so passing
        # ``--log-file /abs/path/log.json`` writes there directly.
        _log_dir_arg = getattr(args, "log_dir", None)
        try:
            log_dir = Path(_log_dir_arg) if _log_dir_arg else Path("./logs")
        except TypeError:
            log_dir = Path("./logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        _fmt_raw = getattr(args, "log_format", None)
        _fmt_str = (
            (str(_fmt_raw) if isinstance(_fmt_raw, str) else "text").split(",")[0].strip().lower()
        )
        _log_format = {"json": LogFormat.JSON, "html": LogFormat.HTML}.get(_fmt_str, LogFormat.TEXT)
        _log_file_raw = getattr(args, "log_file", None)
        _log_file_pattern = _log_file_raw if isinstance(_log_file_raw, str) else None
        logger = DbliftLogger(
            logfile_dir=log_dir, format=_log_format, log_file_pattern=_log_file_pattern
        )

        # Create config from arguments
        try:
            config = load_config(getattr(args, "config", None), args)

            # Check if we have enough information to connect.
            # SQLite can use a file path, not a server/URL.
            # CosmosDB uses account_endpoint, not url/server.
            _db_type_lower = (config.database.type or "").lower()
            _has_path = getattr(config.database, "path", None) or getattr(
                config.database, "database", None
            )
            _quirks = ProviderRegistry.get_quirks(_db_type_lower)
            _url_optional_for_path = _quirks.url_optional_when_file_path_given
            _has_connection_identifier = _quirks.has_connection_identifier(config.database)
            _has_endpoint = getattr(config.database, "account_endpoint", None)
            if (
                not config.database.url
                and not (_url_optional_for_path and _has_path)
                and not _has_endpoint
                and (not config.database.type or not _has_connection_identifier)
            ):
                error_message = (
                    "Missing required connection parameters. Either provide --db-url or --config."
                )
                out.error(error_message)
                results["error"] = error_message
                print_connection_results(results, out)
                return 1

            results["connection_info"]["config_source"] = "Created from provided parameters"
        except Exception as e:
            out.error(f"Error creating configuration: {str(e)}")
            results["error"] = str(e)
            print_connection_results(results, out)
            return 1

        # Validate database type
        if not config.database.type:
            error_message = "Missing database type. Please provide --db-type or a configuration with database type."
            out.error(error_message)
            results["error"] = error_message
            print_connection_results(results, out)
            return 1

        db_type = config.database.type.lower()

        # Create database provider via registry (DIP — no concrete plugin imports)
        try:
            provider: Any = ProviderRegistry.create_provider(config, logger)
        except ValueError as e:
            results["error"] = str(e)
            print_connection_results(results, out)
            return 1

        # Test connection. Format known driver errors as a one-line message so the CLI doesn't
        # dump a Python traceback to stderr on e.g. connection refused / auth failure.
        try:
            provider.create_connection()
        except Exception as connection_error:
            friendly = _format_connection_error(connection_error, db_type)
            out.error(friendly)
            results["error"] = friendly
            print_connection_results(results, out)
            if getattr(args, "log_level", "info") == "debug":
                traceback.print_exc()
            return 1

        try:
            # Get database version and URL before updating results
            version = provider.get_database_version()
            database_url = get_provider_display_url(provider, config) or config.database.url

            # Update results atomically once all operations succeed
            results["success"] = True
            results["connection_info"]["database_url"] = (
                mask_database_url(database_url) if database_url else database_url
            )
            results["connection_info"]["db_type"] = db_type
            schema = getattr(config.database, "schema", None)
            if schema:
                results["connection_info"]["schema"] = schema
            results["database_info"]["version"] = version
        finally:
            # Close connection even if get_database_version/display URL lookup raises
            provider.close()

        # Print results in requested format
        print_connection_results(results, out)
        return 0

    except Exception as e:
        out.error(f"Error testing connection: {str(e)}")
        if getattr(args, "log_level", "info") == "debug":
            traceback.print_exc()
        return 1


# Re-exported so ``db check-connection`` and every other command's own
# connection-establishment step (``BaseCommand._ensure_connected``) format
# connection failures identically. See ``db.error.format_connection_error``
# for the SQLState references and auth-classification rationale.
_format_connection_error = format_connection_error


def print_connection_results(results: Dict[str, Any], out: CommandOutput) -> None:
    """Emit connection test results via the routing abstraction.

    Args:
        results: Connection test results dictionary
        out: The :class:`CommandOutput` constructed from CLI args.
            ``out.output_format`` decides between JSON (machine), pretty
            Python repr (legacy debug), or human text.
    """
    fmt = out.output_format
    if fmt == "json":
        out.machine(results)
    elif fmt == "pretty":
        # Same rationale as in ``diagnose_connection``: format with pprint, emit
        # via ``out`` so injected stdout streams (tests, piping) are honoured.
        out.status(pprint.pformat(results))
    else:  # Default text format
        out.status("\n=== DATABASE CONNECTION TEST ===\n")

        if results["success"]:
            out.status("✅ Connection successful!")
        else:
            out.status("❌ Connection failed!")
            if results["error"]:
                out.status(f"Error: {results['error']}")

        out.status("\nConnection Information:")
        for key, value in results.get("connection_info", {}).items():
            out.status(f"  {key}: {value}")

        if results["success"]:
            out.status("\nDatabase Information:")
            for key, value in results.get("database_info", {}).items():
                out.status(f"  {key}: {value}")

        out.status("\n=== END OF REPORT ===\n")


def setup_db_utils_parser(db_subparsers: Any) -> None:
    """Set up the database utilities subcommands.

    Args:
        db_subparsers: argparse subparsers action group to add db subcommands to
    """
    # List drivers command
    list_parser = db_subparsers.add_parser("list-drivers", help="List native Python drivers")
    list_parser.set_defaults(func=list_drivers)

    # Validate configuration command
    validate_parser = db_subparsers.add_parser(
        "validate-config", help="Validate configuration file"
    )
    # Add standard database configuration arguments
    # Note: --config is intentionally absent here — it is handled by the top-level
    # parser (global_only_args) and forwarded via args.config. Adding it here would
    # cause argparse to overwrite args.config with None (the subparser default).
    validate_parser.add_argument("--db-url", help="Database connection URL")
    validate_parser.add_argument("--db-schema", help="Database schema")
    validate_parser.add_argument("--db-username", help="Database username")
    validate_parser.add_argument("--db-password", help="Database password")
    validate_parser.set_defaults(func=validate_config)

    # Diagnose native driver environment command.
    diagnose_parser = db_subparsers.add_parser(
        "diagnose-connection",
        help="Perform detailed diagnosis of native driver availability",
    )
    diagnose_parser.add_argument(
        "--format",
        choices=["text", "json", "pretty"],
        default="text",
        help="Output format (default: text)",
    )
    diagnose_parser.set_defaults(func=diagnose_connection)

    # Test connection command
    test_parser = db_subparsers.add_parser("check-connection", help="Test database connection")
    # Note: --config is intentionally absent here — it is handled by the top-level
    # parser (global_only_args) and forwarded via args.config. Adding it here would
    # cause argparse to overwrite args.config with None (the subparser default).
    test_parser.add_argument("--db-url", "--url", help="Database connection URL")
    test_parser.add_argument("--db-schema", help="Database schema")
    test_parser.add_argument("--db-username", "--username", help="Database username")
    test_parser.add_argument("--db-password", "--password", help="Database password")
    test_parser.add_argument(
        "--format",
        choices=["text", "json", "pretty"],
        default="text",
        help="Output format (default: text)",
    )
    test_parser.set_defaults(func=check_connection)
