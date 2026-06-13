"""Main client for programmatic access to DBLift."""

from functools import wraps
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Self,
    TypeVar,
    Union,
    cast,
)

from api._client_factory import (
    apply_ctor_overrides,
    build_default_logger,
    client_from_config,
    client_from_config_file,
    client_from_sqlalchemy,
    normalize_migrations_dirs,
    resolve_config_or_raise,
)
from api._client_operations import (
    generate_undo_script_operation,
    generate_undo_scripts_operation,
)
from api.events import EventEmitter, EventType, use_client_emitter
from config import DbliftConfig
from core.logger.results import (
    BaselineResult,
    CleanResult,
    GenerateUndoScriptResult,
    InfoResult,
    MigrateResult,
    OperationResult,
    RepairResult,
    UndoResult,
    ValidateResult,
)
from core.migration.executor.migration_executor import MigrationExecutor
from db.base_provider import BaseProvider
from db.provider_interfaces import ConnectionProvider, TransactionalProvider

__all__ = ["DBLiftClient"]

_F = TypeVar("_F", bound=Callable[..., Any])


def _with_client_emitter(method: _F) -> _F:
    """Bind ``self.events`` as the active emitter for the duration of *method*.

    Cursor-bot finding (api/client.py:141): the class docstring claimed
    "every public operation wraps its body in ``use_client_emitter``",
    but only ``migrate`` and ``undo`` actually did. Any core-layer
    ``emit_event`` raised from ``clean`` / ``info`` / ``validate`` /
    ``diff`` / ``repair`` / ``baseline`` / ``import_flyway`` /
    ``export_schema`` / ``snapshot`` would land on the process-wide
    default emitter, breaking the per-client isolation guarantee.
    Decorating every public operation restores that invariant once and
    keeps it enforced by location instead of by convention.
    """

    @wraps(method)
    def wrapper(self: "DBLiftClient", *args: Any, **kwargs: Any) -> Any:
        # ``getattr`` instead of ``self.events`` so tests that bypass
        # ``__init__`` (e.g. ``DBLiftClient.__new__`` followed by direct
        # method calls) keep working — ``use_client_emitter(None)`` is a
        # documented no-op.
        emitter = getattr(self, "events", None)
        with use_client_emitter(emitter):
            return method(self, *args, **kwargs)

    return cast(_F, wrapper)


class DBLiftClient:
    """Main client for programmatic access to DBLift.

    This class provides a clean Python API for using DBLift programmatically,
    enabling integration with IDEs, CI/CD pipelines, and other development tools.

    Example:
        >>> from api import DBLiftClient
        >>> from config import DbliftConfig
        >>>
        >>> # Use factory method (recommended)
        >>> client = DBLiftClient.from_config_file("dblift.yaml")
        >>>
        >>> # Apply migrations
        >>> result = client.migrate()
        >>> print(f"Applied {len(result.migrations_applied)} migrations")
    """

    def __init__(
        self,
        provider: "BaseProvider",
        migrations_dir: Union[str, Path, List[Union[str, Path]]],
        config: Optional["DbliftConfig"] = None,
        logger: Optional[Any] = None,
        log_level: Optional[str] = None,
        log_format: Optional[str] = None,
        log_file: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize DBLift client.

        Args:
            provider: Database provider instance (e.g., PostgreSqlProvider)
            migrations_dir: Path(s) to migration scripts directory
            config: Optional configuration object (defaults to provider's config)
            logger: Optional logger instance (if None, creates one)
            log_level: Log level (DEBUG, INFO, WARN, ERROR); omit to keep ``config`` values
            log_format: Log format (text, json, html); omit to keep ``config`` values
            log_file: Optional log file path; omit to keep ``config`` values
            **kwargs: Additional configuration options
        """
        # Resolve config before logger so defaults come from merged config (e.g. from file).
        config = resolve_config_or_raise(provider, config)

        if logger is None:
            logger = build_default_logger(config, log_level, log_format, log_file)

        normalize_migrations_dirs(config, migrations_dir)
        apply_ctor_overrides(config, kwargs, log_level, log_format, log_file)

        self.config = config
        self.logger = logger
        self.provider = provider

        # Create executor with injected provider (Dependency Injection)
        self.executor = MigrationExecutor(
            provider=self.provider,
            config=config,
            log=logger,  # Inject provider
        )

        # Normalize dialect once at boundary; methods use self.dialect directly
        self.dialect = self._get_dialect_for_sql_generation()

        # Event system for IDE/tooling. Each client owns a per-instance emitter
        # so listeners registered on one client never see events raised by a
        # sibling client. Core-layer events surface here because every public
        # operation is decorated with ``@_with_client_emitter`` (see top of
        # this module), which binds ``self.events`` to a context variable
        # that ``emit_event`` reads. The decorator covers all public
        # operations — adding a new one without ``@_with_client_emitter``
        # would silently route core-layer events to the process-wide default.
        self.events = EventEmitter()

    def _get_scripts_dir(self) -> Path:
        """Get primary scripts directory.

        Returns:
            Path to scripts directory
        """
        return Path(self.config.migrations.directory)

    def _guard_scripts_dir_kwarg(self, kwargs: Dict[str, Any]) -> None:
        """Raise a clear error if a caller passes ``scripts_dir`` via kwargs.

        BUG-01: Public API methods bind ``scripts_dir`` from client config and
        forward ``**kwargs`` to the executor. A caller-supplied ``scripts_dir``
        collides with the bound keyword, raising a confusing
        ``TypeError: ... got multiple values for keyword argument 'scripts_dir'``.
        Intercept and raise a pointed error directing the caller to
        ``migrations_dir`` at client construction time.
        """
        if "scripts_dir" in kwargs:
            raise TypeError(
                "scripts_dir is not a valid per-call override. "
                "Configure migrations_dir at client construction "
                "(DBLiftClient(..., migrations_dir=...))."
            )

    def _get_dialect_for_sql_generation(self) -> str:
        """Get SQL dialect from provider or config for SQL generation.

        When provider.dialect is a non-None value (including empty string),
        uses it directly. When provider.dialect is None or missing, falls
        through to config.database.type. Always returns lowercase for
        consistency with downstream consumers.
        Raises if config.database.type is explicitly set but empty.

        Returns:
            Dialect string (e.g. 'postgresql', 'mysql')

        Raises:
            ValueError: If config.database.type exists but is empty
        """
        provider_dialect = getattr(self.provider, "dialect", None)
        if provider_dialect is not None:
            return str(provider_dialect).lower()
        config = getattr(self.provider, "config", None)
        database = getattr(config, "database", None) if config else None
        config_dialect = getattr(database, "type", None) if database else None
        if config_dialect == "":
            raise ValueError(
                "Database type is configured but empty. Please set config.database.type to a valid dialect."
            )
        return (
            # lint: allow-dialect-string: dialect dispatch
            config_dialect
            # lint: allow-dialect-string: dialect dispatch
            or "postgresql"
        ).lower()  # lint: allow-dialect-string: dialect dispatch

    @_with_client_emitter
    def migrate(
        self,
        target_version: Optional[str] = None,
        dry_run: bool = False,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        mark_as_executed: bool = False,
        show_sql: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        **kwargs: Any,
    ) -> MigrateResult:
        """Apply pending migrations.

        Args:
            target_version: Target version to migrate to
            dry_run: If True, don't actually apply migrations
            tags: Comma-separated tags to include (e.g., "tag1,tag2")
            exclude_tags: Comma-separated tags to exclude (e.g., "tag1,tag2")
            versions: Comma-separated versions to include (e.g., "1.0.0,1.1.0")
            exclude_versions: Comma-separated versions to exclude (e.g., "1.0.0,1.1.0")
            mark_as_executed: Mark migrations as executed without running them
            show_sql: Include migration SQL statements in outputs and reports
            placeholders: Placeholder values for migration scripts
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            **kwargs: Additional options

        Returns:
            MigrateResult with details of applied migrations
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "target_version": target_version,
                "dry_run": dry_run,
                "show_sql": show_sql,
                "tags": tags,
            },
        )

        try:
            # ``self.events`` is bound as the active emitter for the whole
            # method by ``@_with_client_emitter`` — core-layer ``emit_event``
            # calls (e.g. ``migration.script.*``) land here instead of the
            # process-wide default emitter shared by every client instance.
            result = self.executor.migrate(
                scripts_dir=self._get_scripts_dir(),
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                mark_as_executed=mark_as_executed,
                show_sql=show_sql,
                placeholders=placeholders,
                recursive=recursive,
                additional_dirs=additional_dirs,
                **kwargs,
            )

            if result.success:
                self.events.emit(
                    EventType.MIGRATION_COMPLETED,
                    {
                        "result": result,
                        "migrations_applied": getattr(result, "migrations_applied", []),
                    },
                )
            else:
                self.events.emit(
                    EventType.MIGRATION_FAILED,
                    {
                        "error": getattr(result, "error_message", None),
                        "target_version": target_version,
                    },
                )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "target_version": target_version,
                },
            )
            raise

    @_with_client_emitter
    def info(
        self,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        display_human: bool = False,
        **kwargs: Any,
    ) -> InfoResult:
        """Get migration status information.

        Args:
            target_version: Target version to check
            tags: Comma-separated tags to include (e.g., "tag1,tag2")
            exclude_tags: Comma-separated tags to exclude (e.g., "tag1,tag2")
            versions: Comma-separated versions to include (e.g., "1.0.0,1.1.0")
            exclude_versions: Comma-separated versions to exclude (e.g., "1.0.0,1.1.0")
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            display_human: When True, also prints a human-readable migration
                table to stdout. Defaults to False so programmatic API callers
                get a clean ``InfoResult`` without side effects; the CLI
                handler explicitly enables it for human output.
            **kwargs: Additional options

        Returns:
            InfoResult with migration status
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.INFO_STARTED,
            {
                "target_version": target_version,
                "tags": tags,
            },
        )

        try:
            result = self.executor.info(
                scripts_dir=self._get_scripts_dir(),
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                recursive=recursive,
                additional_dirs=additional_dirs,
                display_human=display_human,
                **kwargs,
            )

            self.events.emit(EventType.INFO_COMPLETED, {"result": result})

            return result
        except Exception as e:
            self.events.emit(EventType.INFO_FAILED, {"error": str(e)})
            raise

    @_with_client_emitter
    def validate(
        self,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        **kwargs: Any,
    ) -> ValidateResult:
        """Validate migration scripts.

        Args:
            target_version: Target version to validate
            tags: Comma-separated tags to include (e.g., "tag1,tag2")
            exclude_tags: Comma-separated tags to exclude (e.g., "tag1,tag2")
            versions: Comma-separated versions to include (e.g., "1.0.0,1.1.0")
            exclude_versions: Comma-separated versions to exclude (e.g., "1.0.0,1.1.0")
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            **kwargs: Additional options

        Returns:
            ValidateResult with validation status
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(EventType.VALIDATION_STARTED, {})

        try:
            result = self.executor.validate(
                scripts_dir=self._get_scripts_dir(),
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                recursive=recursive,
                additional_dirs=additional_dirs,
                **kwargs,
            )

            self.events.emit(EventType.VALIDATION_COMPLETED, {"result": result})

            return result
        except Exception as e:
            self.events.emit(EventType.VALIDATION_FAILED, {"error": str(e)})
            raise

    @_with_client_emitter
    def undo(
        self,
        target_version: Optional[str] = None,
        dry_run: bool = False,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        show_sql: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        **kwargs: Any,
    ) -> "UndoResult":
        """Rollback migrations.

        Args:
            target_version: Target version to rollback to
            dry_run: If True, don't actually rollback migrations
            tags: Comma-separated tags to include (e.g., "tag1,tag2")
            exclude_tags: Comma-separated tags to exclude (e.g., "tag1,tag2")
            versions: Comma-separated versions to include (e.g., "1.0.0,1.1.0")
            exclude_versions: Comma-separated versions to exclude (e.g., "1.0.0,1.1.0")
            show_sql: Include undo SQL statements in outputs and reports
            placeholders: Placeholder values for migration scripts
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            **kwargs: Additional options

        Returns:
            UndoResult with details of rolled back migrations
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "target_version": target_version,
                "dry_run": dry_run,
                "show_sql": show_sql,
                "operation": "undo",
            },
        )

        try:
            # ``self.events`` is bound by ``@_with_client_emitter``.
            result = self.executor.undo(
                scripts_dir=self._get_scripts_dir(),
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                show_sql=show_sql,
                placeholders=placeholders,
                recursive=recursive,
                additional_dirs=additional_dirs,
                **kwargs,
            )

            if result.success:
                self.events.emit(
                    EventType.MIGRATION_COMPLETED,
                    {
                        "result": result,
                        "operation": "undo",
                    },
                )
            else:
                self.events.emit(
                    EventType.MIGRATION_FAILED,
                    {
                        "error": getattr(result, "error_message", None),
                        "operation": "undo",
                    },
                )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "operation": "undo",
                },
            )
            raise

    @_with_client_emitter
    def generate_undo_script(
        self,
        migration_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> "GenerateUndoScriptResult":
        """Generate an undo script for a versioned migration.

        Args:
            migration_path: Path to the versioned SQL migration file (V*__.sql)
            output_dir: Directory to write undo script (default: same as migration file)
            overwrite: Whether to overwrite existing undo script
            **kwargs: Additional options

        Returns:
            GenerateUndoScriptResult with details of the generated undo script

        Raises:
            FileNotFoundError: If ``migration_path`` does not exist (after emitting
                ``MIGRATION_FAILED``). Callers using try/except or batch flows rely on this.

        Example:
            >>> client = DBLiftClient.from_config_file("dblift.yaml")
            >>> result = client.generate_undo_script(
            ...     "migrations/V1_0_1__Create_table.sql",
            ...     overwrite=True
            ... )
            >>> print(f"Generated: {result.undo_script_path}")
        """
        return generate_undo_script_operation(
            self,
            migration_path=migration_path,
            output_dir=output_dir,
            overwrite=overwrite,
        )

    @_with_client_emitter
    def generate_undo_scripts(
        self,
        migration_paths: Optional[List[Union[str, Path]]] = None,
        migrations_dir: Optional[Union[str, Path]] = None,
        overwrite: bool = False,
        recursive: bool = True,
        **kwargs: Any,
    ) -> List["GenerateUndoScriptResult"]:
        """Generate undo scripts for one or more versioned migrations.

        Args:
            migration_paths: List of paths to versioned SQL migration files (V*__.sql).
                             If None, finds all versioned SQL migrations in migrations_dir.
            migrations_dir: Directory to search for migrations (default: configured migrations dir)
            overwrite: Whether to overwrite existing undo scripts
            recursive: Search migrations directory recursively
            **kwargs: Additional options

        Returns:
            List of GenerateUndoScriptResult, one for each migration processed

        Example:
            >>> client = DBLiftClient.from_config_file("dblift.yaml")
            >>> # Generate undo scripts for specific migrations
            >>> results = client.generate_undo_scripts(
            ...     migration_paths=[
            ...         "migrations/V1_0_1__Create_table.sql",
            ...         "migrations/V1_0_2__Add_column.sql"
            ...     ],
            ...     overwrite=True
            ... )
            >>> # Or generate for all versioned migrations
            >>> results = client.generate_undo_scripts(overwrite=True)
            >>> print(f"Generated {len(results)} undo scripts")
        """
        return generate_undo_scripts_operation(
            self,
            migration_paths=migration_paths,
            migrations_dir=migrations_dir,
            overwrite=overwrite,
            recursive=recursive,
            **kwargs,
        )

    @_with_client_emitter
    def clean(
        self,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        clean_enabled: bool = False,
        **kwargs: Any,
    ) -> "CleanResult":
        """Clean database schema.

        Args:
            dry_run: If True, don't actually clean the database
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            clean_enabled: If True, allow destructive clean even when config disables it
            **kwargs: Additional options

        Returns:
            CleanResult with details of cleaned objects
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "operation": "clean",
                "dry_run": dry_run,
            },
        )

        try:
            result = self.executor.clean(
                scripts_dir=self._get_scripts_dir(),
                dry_run=dry_run,
                recursive=recursive,
                additional_dirs=additional_dirs,
                clean_enabled=clean_enabled,
                **kwargs,
            )

            self.events.emit(
                EventType.MIGRATION_COMPLETED,
                {
                    "result": result,
                    "operation": "clean",
                },
            )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "operation": "clean",
                },
            )
            raise

    @_with_client_emitter
    def baseline(
        self,
        version: str,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> "BaselineResult":
        """Baseline an existing database.

        Args:
            version: Version to baseline at
            description: Optional description for baseline
            **kwargs: Additional options

        Returns:
            BaselineResult with baseline details
        """
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "operation": "baseline",
                "version": version,
            },
        )

        try:
            result = self.executor.baseline(
                baseline_version=version,
                baseline_description=description or "",
                **kwargs,
            )

            self.events.emit(
                EventType.MIGRATION_COMPLETED,
                {
                    "result": result,
                    "operation": "baseline",
                },
            )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "operation": "baseline",
                },
            )
            raise

    @_with_client_emitter
    def repair(
        self,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        **kwargs: Any,
    ) -> "RepairResult":
        """Repair the schema history table.

        Args:
            dry_run: If True, don't actually repair
            recursive: Search scripts directory recursively
            additional_dirs: Additional script directories
            dir_recursive_map: Map of directories to recursive settings
            **kwargs: Additional options

        Returns:
            RepairResult with repair details
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "operation": "repair",
                "dry_run": dry_run,
            },
        )

        try:
            result = self.executor.repair(
                scripts_dir=self._get_scripts_dir(),
                dry_run=dry_run,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
                **kwargs,
            )

            self.events.emit(
                EventType.MIGRATION_COMPLETED,
                {
                    "result": result,
                    "operation": "repair",
                },
            )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "operation": "repair",
                },
            )
            raise

    @_with_client_emitter
    def import_flyway(
        self,
        dry_run: bool = False,
        recursive: bool = True,
        flyway_table: str = "flyway_schema_history",
        **kwargs: Any,
    ) -> "OperationResult":
        """Import Flyway schema history.

        Args:
            dry_run: If True, don't actually import
            recursive: Search scripts directory recursively
            flyway_table: Source Flyway history table name
            **kwargs: Additional options

        Returns:
            OperationResult with import details
        """
        self._guard_scripts_dir_kwarg(kwargs)
        self.events.emit(
            EventType.MIGRATION_STARTED,
            {
                "operation": "import_flyway",
                "dry_run": dry_run,
            },
        )

        try:
            result = self.executor.import_flyway(
                scripts_dir=self._get_scripts_dir(),
                dry_run=dry_run,
                flyway_table=flyway_table,
            )

            self.events.emit(
                EventType.MIGRATION_COMPLETED,
                {
                    "result": result,
                    "operation": "import_flyway",
                },
            )

            return result
        except Exception as e:
            self.events.emit(
                EventType.MIGRATION_FAILED,
                {
                    "error": str(e),
                    "operation": "import_flyway",
                },
            )
            raise

    @_with_client_emitter
    def from_config(
        cls,
        config: "DbliftConfig",
        logger: Optional[Any] = None,
        migrations_dir: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        **kwargs: Any,
    ) -> Self:
        """Create a client instance from existing configuration.

        Args:
            config: DbliftConfig instance.
            logger: Optional logger. When ``None`` a DbliftLogger is built
                from the config's log settings.
            migrations_dir: Override for the migrations directory (or list of
                directories). When omitted, falls back to
                ``config.migrations.directory`` and
                ``config.migrations.directories``.
            **kwargs: Forwarded to the client constructor.

        BUG-07: ``migrations_dir`` used to be undocumented — it was honored
        only because the factory popped it from ``kwargs``. Making it an
        explicit parameter keeps Python tooling (type checkers, IDEs,
        ``help()``) honest and prevents users from silently falling back to
        the configured directory when they mistype the keyword.
        """
        if migrations_dir is not None:
            kwargs["migrations_dir"] = migrations_dir
        return cast(
            Self,
            client_from_config(config, logger, client_cls=cls, **kwargs),
        )

    @classmethod
    def from_config_file(
        cls,
        config_path: str,
        logger: Optional[Any] = None,
        **overrides: Any,
    ) -> Self:
        """Create a client instance from config file path."""
        return cast(
            Self,
            client_from_config_file(config_path, logger, client_cls=cls, **overrides),
        )

    @classmethod
    def from_sqlalchemy(
        cls,
        engine: Any = None,
        migrations_dir: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        schema: Optional[str] = None,
        logger: Optional[Any] = None,
        log_level: str = "INFO",
        log_format: str = "text",
        log_file: Optional[str] = None,
        *,
        connection: Any = None,
        config: Optional["DbliftConfig"] = None,
        **kwargs: Any,
    ) -> Self:
        """Create DBLiftClient from an existing SQLAlchemy Engine (or Connection).

        This is the primary Python-native integration API. The caller owns the
        Engine lifecycle; closing the returned client will not dispose the
        engine.

        Example:
            from sqlalchemy import create_engine
            from api import DBLiftClient

            engine = create_engine("postgresql+psycopg://...")
            with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
                client.migrate()
        """
        return cast(
            Self,
            client_from_sqlalchemy(
                engine,
                migrations_dir,
                schema,
                logger,
                log_level,
                log_format,
                log_file,
                connection=connection,
                config=config,
                client_cls=cls,
                **kwargs,
            ),
        )

    # Phase 2.4: Context Manager Support

    def __enter__(self) -> "DBLiftClient":
        """Context manager entry: ensure provider connection.

        Example:
            >>> with DBLiftClient.from_config_file("dblift.yaml") as client:
            ...     result = client.migrate()
            ...     # Connection automatically closed on exit
        """
        # Ensure provider has a connection (avoid creating when already connected)
        if isinstance(self.provider, ConnectionProvider):
            try:
                is_conn = self.provider.is_connected()
            except Exception as e:
                # is_connected() raised (e.g. state unknown) — log and try to connect
                self.logger.debug(f"Could not check connection state in __enter__: {e}")
                self.provider.create_connection()
            else:
                if not is_conn:
                    self.provider.create_connection()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        """Context manager exit: close provider connection and handle exceptions.

        If an exception occurred during the context, automatically rollback any
        active transaction. Otherwise, ensure proper cleanup.

        Args:
            exc_type: Exception type if an exception occurred, None otherwise
            exc_val: Exception value if an exception occurred, None otherwise
            exc_tb: Exception traceback if an exception occurred, None otherwise
        """
        if exc_type is not None:
            # Exception occurred, rollback any pending transaction
            self.logger.warning(f"Exception in DBLiftClient context: {exc_val}")

            try:
                if isinstance(self.provider, TransactionalProvider):
                    self.provider.rollback_transaction()
            except Exception as rollback_error:
                self.logger.error(f"Error during rollback in __exit__: {rollback_error}")

        # Close the provider connection
        try:
            if isinstance(self.provider, ConnectionProvider):
                self.provider.close()
        except Exception as close_error:
            self.logger.warning(f"Error closing provider in __exit__: {close_error}")

        # Don't suppress the exception - return None (default for __exit__)
        return None

    def close(self) -> None:
        """Release resources held by this client."""
        self.__exit__(None, None, None)
