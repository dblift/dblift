"""
Base provider interface for all database providers.

This module defines the common provider contract and the transport-family
markers used by DBLift's registry. Database providers expose SQL semantics;
native providers use drivers, SDKs, or embedded APIs behind the same boundary.

BaseProvider hérite des 5 interfaces focalisées (ISP) :
    ConnectionProvider, QueryProvider, SchemaProvider,
    TransactionalProvider, MigrationProvider

Les providers concrets (SQLAlchemy, CosmosDB, SQLite) héritent de BaseProvider.
Pour vérifier les capacités, utiliser isinstance :
    isinstance(provider, TransactionalProvider)
"""

from abc import abstractmethod
from typing import Any, Optional

from config import DbliftConfig
from core.logger import Log, NullLog
from db.base_quirks import BaseQuirks
from db.provider_interfaces import (
    ConnectionProvider,
    MigrationProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
)


class BaseProvider(
    ConnectionProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
    MigrationProvider,
):
    """Base pour tous les providers — hérite des 5 interfaces focalisées.

    Les providers concrets (SQLAlchemy, CosmosDB, SQLite) héritent de BaseProvider.
    Pour vérifier les capacités, utiliser isinstance :
        isinstance(provider, TransactionalProvider)
    """

    #: Canonical dialect key for the database this provider talks to.
    #:
    #: Each plugin's concrete provider class declares its own dialect here
    #: (e.g. ``OracleProvider.canonical_dialect_key = "oracle"``). This
    #: is the **single source of truth** the framework consults when it
    #: needs the dialect name — no string matching, no URL sniffing in
    #: framework code (Epic 26 dialect isolation).
    #:
    #: Defaults to an empty string so generic providers / test fakes that
    #: don't override it fall through to the legacy detection cascade in
    #: ``MigrationExecutionEngine._probe_dialect_key``.
    canonical_dialect_key: str = ""

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the provider with configuration.

        Args:
            config: Application configuration
            log: Optional logger
        """
        self.config = config
        self.log = log if log is not None else NullLog()

        if not isinstance(config, DbliftConfig):
            raise TypeError("config must be an instance of DbliftConfig")
        if not hasattr(config, "database") or not config.database:
            raise ValueError("config must have a database attribute")
        if not hasattr(config.database, "type") or not config.database.type:
            raise ValueError("config.database must have a type attribute")
        # Epic 26: cache for the dialect-quirks overlay. Lazy because
        # ProviderRegistry imports BaseProvider — resolving on
        # construction would force a circular import at module load.
        self._quirks: Optional[BaseQuirks] = None

    provider_transport = "native"

    @property
    def quirks(self) -> BaseQuirks:
        """Behaviour-overlay for this provider's dialect (Epic 26).

        Framework code calls ``provider.quirks.<hook>(...)`` instead of
        branching on ``self.config.database.type``. The instance is
        resolved once via :meth:`db.provider_registry.ProviderRegistry.get_quirks`
        and cached. Plugins without a declared ``quirks_class`` get a
        :class:`BaseQuirks` instance — every call site is branch-free.
        """
        if self._quirks is None:
            from db.provider_registry import ProviderRegistry

            self._quirks = ProviderRegistry.get_quirks(self.config.database.type)
        return self._quirks

    def get_display_url(self) -> str:
        """Return a neutral provider URL for logs, reports, and CLI output.

        Providers may override this to return SDK endpoints, SQLAlchemy URLs,
        or local file paths without exposing driver-specific APIs.
        """
        db = getattr(self.config, "database", None)
        if db is None:
            return ""

        for attr in ("url", "account_endpoint", "path", "database"):
            value = getattr(db, attr, None)
            if value is not None and str(value).strip():
                return str(value)
        return ""

    def get_normalized_object_name(self, object_name: str) -> str:
        """Return the correct object name for this database's naming convention.

        Use this when resolving object names (e.g. history table, lock table)
        to ensure the correct case is used for the target database.

        Args:
            object_name: Base object name (e.g., "dblift_schema_history")

        Returns:
            Object name with appropriate case for this database
        """
        from db.object_naming import get_normalized_object_name

        dialect = getattr(self.config.database, "type", "postgresql")
        return get_normalized_object_name(object_name, dialect)

    @abstractmethod
    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            schema: Schema name
            create_schema: Whether this is called from the baseline command
            table_name: Custom history table name (default: dblift_schema_history)
        """

    def create_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table if it doesn't exist.

        Args:
            schema: Schema name
            create_schema: Whether to create the schema if it doesn't exist (default: False)
            table_name: History table name (default: dblift_schema_history)
        """
        self.create_migration_history_table_if_not_exists(schema, create_schema, table_name)

    @abstractmethod
    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the schema snapshot storage table if it does not exist.

        All concrete providers **must** implement this method.
        Mirrors the contract of ``create_migration_history_table_if_not_exists``.

        Args:
            schema: Schema name
            table_name: Table name for snapshots (default: dblift_schema_snapshots)
        """

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record an undo operation in the migration history table.

        Default delegates to ``self.history_manager.record_undo`` with
        ``self.connection``. ``BaseHistoryManager.record_undo`` already creates
        a synthetic ``UNDO_SQL`` row through ``record_migration``, so any
        provider that owns a ``history_manager`` and ``connection`` inherits
        a working implementation for free. Without this default each provider
        had to wire the same delegation by hand — and any that forgot
        (SQLite did, CosmosDB still would) crashed with ``AttributeError``
        when ``MigrationHistoryManager.record_undo`` tried to dispatch.

        Providers with non-trivial undo semantics run a
        re-apply detection query first; Oracle/SQL Server intentionally
        bypass that complex path) keep their own override.

        Args:
            schema: Schema name
            version: Version being undone
            table_name: Custom history table name
            script_name: Original migration script name, if available

        Returns:
            True on success, False on failure.
        """
        history_manager = getattr(self, "history_manager", None)
        if history_manager is None:
            raise NotImplementedError(
                f"{type(self).__name__} has no history_manager; "
                "override record_undo or attach a history_manager component."
            )
        connection = getattr(self, "connection", None)
        return bool(
            history_manager.record_undo(connection, schema, version, table_name, script_name)
        )

    def close(self) -> None:
        """Close the database connection if it exists.

        Subclasses that hold a real connection **should** override
        this method to properly release resources.  The default no-op is acceptable
        for providers without a persistent connection (e.g. stateless stubs).
        """
        self.log.debug("Closing database connection")

    def connect(self) -> None:
        """Connect to the database.

        This is a convenience method that calls create_connection().
        """
        self.create_connection()

    def is_connected(self) -> bool:
        """Check if the provider is connected to the database.

        Subclasses that maintain a real connection **should** override this method
        to introspect the live connection state.  The default ``False`` is acceptable
        for providers without a persistent connection (e.g. stateless stubs or
        providers that reconnect on every operation).

        Returns:
            True if connected, False otherwise
        """
        return False  # Default: acceptable for stateless / stub providers

    def __enter__(self) -> Any:
        """Context manager entry: create and return a connection."""
        conn = self.create_connection()
        return conn

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> None:
        """Context manager exit: close the connection."""
        self.close()


class NativeProvider(BaseProvider):
    """Marker base class for SDK/native providers.

    Native providers are first-class DBLift providers, but they are not expected
    to expose database connection objects, driver metadata, or ``get_database_url()``.
    """

    provider_transport = "native"
