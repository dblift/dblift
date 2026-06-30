"""Factory functions for creating DBLiftClient instances.

Extracted from api/client.py (story 20-16) to reduce file size.
Contains the logic behind the from_config, from_config_file, and from_sqlalchemy classmethods.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

from api._engine_config import config_from_engine
from config import DbliftConfig
from config.config_builder import ConfigBuilder
from config.errors import ConfigurationError
from core.logger import DbliftLogger, LogFormat, LogLevel
from db.native_connection_manager import NativeConnectionManager
from db.provider_registry import ProviderRegistry


class _EnumWithFromString(Protocol):
    """Enum-like type with ``from_string`` (e.g. LogFormat, LogLevel)."""

    @classmethod
    def from_string(cls, value: str) -> Any: ...  # noqa: E704


def _resolve_enum_value(raw: Any, enum_class: type[_EnumWithFromString], default: Any) -> Any:
    """Resolve a raw config value (string, enum, or None) to an enum instance."""
    if raw is None:
        return default
    if isinstance(raw, enum_class):
        return raw
    return enum_class.from_string(str(raw).upper())


def _configured_log_directory(config: Any) -> Optional[str]:
    """Return explicit log directory from flat ``log_dir`` or ``logging.directory``."""
    flat = getattr(config, "log_dir", None)
    nested = getattr(getattr(config, "logging", None), "directory", None)
    chosen = flat or nested
    if chosen is None:
        return None
    s = str(chosen).strip()
    return s if s else None


def effective_log_file_from_config(config: Any) -> Optional[str]:
    """Flat ``log_file`` or nested ``logging.file``, mirroring ``client_from_config`` logic."""
    return getattr(config, "log_file", None) or getattr(
        getattr(config, "logging", None), "file", None
    )


def resolve_client_logfile_dir(config: Any, eff_log_file: Optional[str]) -> Optional[Path]:
    """Resolve ``DbliftLogger``'s ``logfile_dir`` from config and optional log file path.

    Absolute log file paths define the directory via their parent. Relative paths that
    are only a file name (parent is ``.``) use :func:`_configured_log_directory` when set.
    When no log file is configured, an explicit log directory still applies.
    """
    eff_log_dir = _configured_log_directory(config)
    if not eff_log_file:
        return Path(eff_log_dir) if eff_log_dir else None
    p = Path(eff_log_file)
    if p.is_absolute():
        return p.parent
    if p.parent != Path("."):
        return p.parent
    if eff_log_dir:
        return Path(eff_log_dir)
    return None


def resolve_config_or_raise(
    provider: Any, explicit_config: Optional["DbliftConfig"]
) -> "DbliftConfig":
    """Return *explicit_config* if non-None, else ``provider.config``, else raise.

    Extracted from ``DBLiftClient.__init__`` to keep the ctor focused on
    wiring. Raising ``ConfigurationError`` here yields the same surface as
    the previous inline check (callers expecting it still pass).
    """
    if explicit_config is not None:
        return explicit_config
    if provider.config is not None:
        return provider.config  # type: ignore[no-any-return]
    raise ConfigurationError("DBLiftClient requires an explicit config or a provider with config")


def build_default_logger(
    config: Any,
    log_level: Optional[str],
    log_format: Optional[str],
    log_file: Optional[str],
) -> DbliftLogger:
    """Construct a ``DbliftLogger`` mirroring ``DBLiftClient.__init__`` defaults.

    Ctor overrides (``log_level`` / ``log_format`` / ``log_file``) take
    precedence over ``config``; ``None`` means "fall back to config".
    """
    raw_fmt = log_format if log_format is not None else getattr(config, "log_format", None)
    log_format_value = _resolve_enum_value(raw_fmt, LogFormat, LogFormat.TEXT)

    raw_lvl = log_level if log_level is not None else getattr(config, "log_level", None)
    log_level_value = _resolve_enum_value(raw_lvl, LogLevel, LogLevel.INFO)

    eff_log_file = log_file if log_file is not None else effective_log_file_from_config(config)
    return DbliftLogger(
        format=log_format_value,
        level=log_level_value,
        logfile_dir=resolve_client_logfile_dir(config, eff_log_file),
    )


def normalize_migrations_dirs(config: Any, migrations_dir: Union[str, Path, List[Any]]) -> None:
    """Normalize ``migrations_dir`` (str/Path/list) and apply to ``config.migrations``.

    First entry becomes ``config.migrations.directory``; remaining entries (if any)
    populate ``config.migrations.directories``. Caller passes the original
    user-facing value; this function performs in-place mutation.
    """
    if isinstance(migrations_dir, (str, Path)):
        migrations_dir = [migrations_dir]
    paths = [_migration_directory_path(d) for d in migrations_dir]
    if paths:
        config.migrations.directory = str(paths[0])
    if len(paths) > 1:
        config.migrations.directories = [str(d) for d in paths[1:]]
    else:
        config.migrations.directories = []


def _migration_directory_path(directory: Any) -> Path:
    if isinstance(directory, (str, Path)):
        return Path(directory)
    if isinstance(directory, dict):
        return Path(directory.get("path", ""))
    path = getattr(directory, "path", None)
    if path is not None:
        return Path(path)
    return Path(directory)


def apply_ctor_overrides(
    config: Any,
    kwargs: Dict[str, Any],
    log_level: Optional[str],
    log_format: Optional[str],
    log_file: Optional[str],
) -> None:
    """Apply ``**kwargs`` config setattr + explicit log_* overrides (in-place).

    ``setattr`` is used so duck-typed configs without declared ``log_*`` fields
    keep working — matches the prior inline logic in ``DBLiftClient.__init__``.
    """
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
    if log_level is not None:
        setattr(config, "log_level", log_level)
    if log_format is not None:
        setattr(config, "log_format", log_format)
    if log_file is not None:
        setattr(config, "log_file", log_file)


def client_from_config(
    config: "DbliftConfig",
    logger: Optional[Any] = None,
    *,
    client_cls: Optional[type] = None,
    **kwargs: Any,
) -> Any:
    """Create a client instance from existing configuration.

    This is the primary factory function for creating a client from an
    existing configuration object. Used by CLI and other entry points.

    Args:
        config: DbliftConfig instance
        logger: Optional logger instance
        client_cls: Concrete client class (defaults to :class:`~api.client.DBLiftClient`)
        **kwargs: Additional options passed to the client constructor

    Returns:
        An instance of ``client_cls`` (or ``DBLiftClient`` when ``client_cls`` is omitted)
    """
    client_config = deepcopy(config)

    # Create logger if not provided
    if logger is None:
        raw_fmt = getattr(config, "log_format", None)
        log_format_value = _resolve_enum_value(raw_fmt, LogFormat, LogFormat.TEXT)
        raw_lvl = getattr(config, "log_level", None)
        log_level = _resolve_enum_value(raw_lvl, LogLevel, LogLevel.INFO)
        eff_log_file = effective_log_file_from_config(config)
        logger = DbliftLogger(
            format=log_format_value,
            level=log_level,
            logfile_dir=resolve_client_logfile_dir(config, eff_log_file),
        )

    provider = ProviderRegistry.create_provider(client_config, logger)

    # Caller-supplied migrations_dir takes priority over config.migrations.directory.
    # Pop it from kwargs now so it is not passed twice to the constructor.
    caller_migrations_dir = kwargs.pop("migrations_dir", None)

    # Get migrations directory from config (used only when caller did not supply one)
    migrations_dir: Union[str, Path, List[Any]] = (
        caller_migrations_dir
        if caller_migrations_dir is not None
        else client_config.migrations.directory
    )
    if caller_migrations_dir is None and hasattr(client_config.migrations, "get_directory_configs"):
        dir_configs = client_config.migrations.get_directory_configs()
        if dir_configs:
            configured_dirs = [dir_config.path for dir_config in dir_configs]
            if configured_dirs:
                migrations_dir = configured_dirs

    # Import here to avoid circular import: api.client imports this module at load time.
    from api.client import DBLiftClient

    ctor = client_cls if client_cls is not None else DBLiftClient

    # Create client using provider (API-first pattern)
    return ctor(
        provider=provider,
        migrations_dir=migrations_dir,
        config=client_config,
        logger=logger,
        **kwargs,
    )


def client_from_config_file(
    config_path: str,
    logger: Optional[Any] = None,
    *,
    client_cls: Optional[type] = None,
    **overrides: Any,
) -> Any:
    """Create a client instance from config file path.

    Args:
        config_path: Path to configuration file
        logger: Optional logger instance
        client_cls: Concrete client class (defaults to :class:`~api.client.DBLiftClient`)
        **overrides: Configuration overrides (database_url, database_schema, etc.)

    Returns:
        An instance of ``client_cls`` (or ``DBLiftClient`` when ``client_cls`` is omitted)
    """
    config = ConfigBuilder.build(file_path=config_path, **overrides)
    # Keys already merged into ``config`` by ConfigBuilder.build must not be passed again
    # to DBLiftClient (would re-apply or confuse nested database_* aliases).
    passthrough = {
        k: v for k, v in overrides.items() if k not in ConfigBuilder.CONFIG_BUILD_KWARG_KEYS
    }
    return client_from_config(config, logger, client_cls=client_cls, **passthrough)


def _attach_external_sqlite_connection(provider: Any, engine: Any, connection: Any) -> None:
    """Bind a caller-owned SQLAlchemy engine/connection to a sqlite3 provider.

    The native ``SQLiteProvider`` extracts the underlying DBAPI
    ``sqlite3.Connection`` from the SQLAlchemy Engine (or Connection) and
    operates on the *same* database as the caller. It also retains the
    engine/connection so it can re-bind on reconnect, and flags the connection
    as caller-owned so ``close()`` never disposes it.
    """
    provider.attach_external_sqlalchemy(engine, connection)


def client_from_sqlalchemy(
    engine: Any = None,
    migrations_dir: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
    schema: Optional[str] = None,
    logger: Optional[Any] = None,
    log_level: str = "INFO",
    log_format: str = "text",
    log_file: Optional[str] = None,
    *,
    connection: Any = None,
    config: Optional[DbliftConfig] = None,
    client_cls: Optional[type[Any]] = None,
    **kwargs: Any,
) -> Any:
    """Create DBLiftClient from an existing SQLAlchemy Engine or Connection.

    Primary integration point for Python application runtimes (FastAPI lifespan,
    pytest fixtures, Flask, etc.). The caller retains ownership of the engine;
    DBLiftClient.close() will not dispose it.

    Accepts either ``engine=`` or ``connection=`` (mutually exclusive).
    """
    if engine is not None and connection is not None:
        raise ConfigurationError("Pass engine or connection, not both")
    if connection is not None:
        engine = getattr(connection, "engine", connection)
    if engine is None:
        raise ConfigurationError("from_sqlalchemy requires engine= or connection=")

    derived = config_from_engine(engine, schema=schema, migrations_dir=migrations_dir)
    if config is not None:
        # Overlay the caller's config without stomping connection identity
        # derived from the injected engine.
        merged = deepcopy(derived)
        database_identity_fields = {
            "url",
            "type",
            "host",
            "port",
            "database",
            "username",
            "password",
            "driver",
            "schema",
        }
        for attr in ("database", "migrations", "logging"):
            if hasattr(config, attr):
                override = getattr(config, attr)
                target = getattr(merged, attr)
                for f in dir(override):
                    if attr == "database" and f in database_identity_fields:
                        continue
                    if not f.startswith("_") and hasattr(override, f):
                        val = getattr(override, f)
                        if val is not None and not callable(val):
                            setattr(target, f, val)
        # Also bring in top-level fields from the override (e.g. placeholders)
        for f in dir(config):
            if not f.startswith("_") and hasattr(config, f):
                val = getattr(config, f)
                if (
                    val is not None
                    and f not in ("database", "migrations", "logging")
                    and not callable(val)
                ):  # noqa: E501
                    setattr(merged, f, val)
        derived = merged

    # Respect explicit logger if provided (matches client_from_config contract).
    # Only fall back to building from log_* params when logger is None.
    if logger is None:
        logger = build_default_logger(derived, log_level, log_format, log_file)

    provider = ProviderRegistry.create_provider(derived, logger)

    # Inject external engine so provider re-uses caller's Engine/Connection
    # (ownership=False prevents dispose on client/provider close).
    if hasattr(provider, "_conn_mgr"):
        provider._conn_mgr = NativeConnectionManager(
            derived, logger, engine=engine, owns_engine=False
        )  # noqa: E501
    elif hasattr(provider, "attach_external_sqlalchemy"):
        # The native SQLite provider talks to ``sqlite3`` directly instead of
        # through a NativeConnectionManager, so the branch above never fires for
        # it. It is the only provider exposing ``attach_external_sqlalchemy`` —
        # the capability of reaching through a caller's SQLAlchemy engine to its
        # underlying DBAPI connection. Without this, the provider would open its
        # *own* ``sqlite3`` connection and migrate a different database than the
        # caller's engine — fatal for ``sqlite:///:memory:`` where every
        # connection is a separate in-memory DB.
        _attach_external_sqlite_connection(provider, engine, connection)

    # When a specific Connection was passed, bind it directly so that
    # immediate provider operations (and thus migrations) run against the
    # caller's live connection/session rather than opening a fresh one from
    # the engine pool. This makes the `connection=` path actually useful.
    # We also set a flag so the provider skips its auto-commit logic
    # (the caller owns the session/tx and is responsible for commit/rollback).
    if connection is not None:
        setattr(provider, "_connection", connection)
        setattr(provider, "_external_connection", True)

    ctor = client_cls or __import__("api.client", fromlist=["DBLiftClient"]).DBLiftClient
    return ctor(
        provider=provider,
        migrations_dir=migrations_dir or getattr(derived.migrations, "directory", None),
        config=derived,
        logger=logger,
        **kwargs,
    )
