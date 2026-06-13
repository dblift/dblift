"""
Base class for database-specific schema introspection.

Provides database-agnostic metadata extraction through plugin-owned
vendor-specific catalog queries.

Post-H.2 and F.3, every dialect decision routes through
:class:`db.base_quirks.BaseQuirks` hooks, so this class itself contains
no ``self.dialect ==`` branches and serves as the canonical concrete
introspector for every plugin. Each plugin's quirks-declared
``<Dialect>Introspector`` is a thin subclass of this one.
"""

from typing import Any, Dict, List, Optional, Type, TypeVar

_T = TypeVar("_T")

from core.introspection._utils import (
    get_row_value,
    parse_json_array,
    parse_pg_options,
    strip_leading_comments,
    to_int,
)
from core.introspection._vendor_property_applier import VendorPropertyApplier
from core.introspection.extractors.column_extractor import ColumnExtractor
from core.introspection.extractors.constraint_extractor import ConstraintExtractor
from core.introspection.extractors.index_extractor import IndexExtractor
from core.introspection.extractors.misc_extractor import MiscExtractor
from core.introspection.extractors.procedure_extractor import ProcedureExtractor
from core.introspection.extractors.sequence_extractor import SequenceExtractor
from core.introspection.extractors.table_extractor import TableExtractor
from core.introspection.extractors.trigger_extractor import TriggerExtractor
from core.introspection.extractors.view_extractor import ViewExtractor
from core.introspection.result import IntrospectionResult, ObjectCaptureStatus
from core.introspection.vendor_queries_factory import VendorQueriesFactory
from core.logger import NullLog
from core.sql_model.base import SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.view import View
from db.provider_capabilities import get_provider_driver_display
from db.provider_interfaces import ConnectionProvider


class BaseIntrospector:
    """
    Canonical concrete introspector for every dialect.

    Built on the vendor-specific catalog queries discovered through
    ``BaseQuirks.vendor_queries_class``. Every
    per-kind ``get_X`` method delegates to a dedicated extractor in
    :mod:`core.introspection.extractors`, and every dialect-specific
    decision lives behind a :class:`BaseQuirks` hook — so this class
    contains zero ``self.dialect ==`` branches.

    Each plugin ships a thin :class:`<Dialect>Introspector` subclass
    under ``db/plugins/<dialect>/introspection/`` and wires it through
    ``<X>Quirks.introspector_class``; the subclass exists so a
    developer reading the plugin directory sees the full surface
    without leaving it.

    Example:
        >>> introspector = PostgreSQLIntrospector(provider)
        >>> tables = introspector.get_tables("public")
        >>> for table in tables:
        ...     print(f"Table: {table.name}, Columns: {len(table.columns)}")
    """

    def __init__(self, provider: Any, log: Any = None, use_vendor_queries: bool = True) -> None:
        """Initialize the base introspector.

        Args:
            provider: Database provider (for connection management)
            log: Optional logger instance
            use_vendor_queries: Whether to use vendor-specific queries for enhanced metadata (default: True)
        """
        self.provider = provider
        self.log = log if log is not None else NullLog()
        self.connection: Any = None
        self.metadata: Any = None
        self.dialect = (
            provider.config.database.type
            if hasattr(provider, "config") and hasattr(provider.config, "database")
            else "unknown"
        )
        self.vendor_queries = None
        if use_vendor_queries:
            self.vendor_queries = VendorQueriesFactory.create(self.dialect)
            if self.vendor_queries:
                self.log.debug(f"Vendor-specific queries enabled for {self.dialect}")
            else:
                self.log.debug(f"No vendor-specific queries available for {self.dialect}")
        self._object_column_cache: Dict[tuple[str, str], List[str]] = {}
        self._current_result: Optional[IntrospectionResult] = None
        self._track_results: bool = False
        self._oracle_package_specs: Dict[tuple[str, str], str] = {}
        self._table_extractor: Optional[TableExtractor] = None
        self._column_extractor: Optional[ColumnExtractor] = None
        self._constraint_extractor: Optional[ConstraintExtractor] = None
        self._index_extractor: Optional[IndexExtractor] = None
        self._view_extractor: Optional[ViewExtractor] = None
        self._sequence_extractor: Optional[SequenceExtractor] = None
        self._trigger_extractor: Optional[TriggerExtractor] = None
        self._procedure_extractor: Optional[ProcedureExtractor] = None
        self._misc_extractor: Optional[MiscExtractor] = None
        self._original_autocommit: Optional[bool] = None

        # Vendor property applier delegate (SRP-02)
        self._vendor_property_applier = VendorPropertyApplier(
            dialect=self.dialect, vendor_queries=self.vendor_queries, log=self.log
        )

    def _get_extractor(self, attr_name: str, extractor_class: Type[_T], **extra_kwargs: Any) -> _T:
        """Generic lazy-init extractor getter with connection/metadata sync.

        On first call, creates the extractor with all standard kwargs plus any extra_kwargs.
        On subsequent calls, syncs connection and metadata on the existing extractor.

        Args:
            attr_name: Name of the instance attribute storing the extractor (e.g. "_column_extractor")
            extractor_class: Class to instantiate on first call
            **extra_kwargs: Additional kwargs passed to extractor_class on creation (ignored on sync)

        Returns:
            The extractor instance (created or existing)
        """
        extractor: Optional[_T] = getattr(self, attr_name)
        if extractor is None:
            # Don't force-connect on construction — each extractor method
            # that actually needs a connection calls ``ensure_metadata()``
            # itself, and the upper-layer ``SchemaIntrospector.get_X``
            # entry points short-circuit on capability flags before even
            # reaching here. Calling ``self._ensure_metadata()`` eagerly
            # made every ``get_unsupported_kind()`` invocation open a
            # connection just to return ``[]`` (Bugbot review on F.3.a).
            extractor = extractor_class(  # type: ignore[call-arg]
                provider=self.provider,
                connection=self.connection,
                metadata=self.metadata,
                vendor_queries=self.vendor_queries,
                dialect=self.dialect,
                log=self.log,
                result_tracker=self if self._track_results else None,
                **extra_kwargs,
            )
            setattr(self, attr_name, extractor)
        else:
            extractor.connection = self.connection  # type: ignore[attr-defined]
            extractor.metadata = self.metadata  # type: ignore[attr-defined]
        return extractor

    def _get_table_extractor(self) -> TableExtractor:
        return self._get_extractor(
            "_table_extractor",
            TableExtractor,
            column_extractor=self._get_column_extractor(),
            constraint_extractor=self._get_constraint_extractor(),
        )

    def _get_column_extractor(self) -> ColumnExtractor:
        return self._get_extractor("_column_extractor", ColumnExtractor)

    def _get_constraint_extractor(self) -> ConstraintExtractor:
        return self._get_extractor("_constraint_extractor", ConstraintExtractor)

    def _get_index_extractor(self) -> IndexExtractor:
        return self._get_extractor("_index_extractor", IndexExtractor)

    def _get_view_extractor(self) -> ViewExtractor:
        return self._get_extractor("_view_extractor", ViewExtractor)

    def _get_sequence_extractor(self) -> SequenceExtractor:
        return self._get_extractor("_sequence_extractor", SequenceExtractor)

    def _get_trigger_extractor(self) -> TriggerExtractor:
        return self._get_extractor("_trigger_extractor", TriggerExtractor)

    def _get_procedure_extractor(self) -> ProcedureExtractor:
        return self._get_extractor("_procedure_extractor", ProcedureExtractor)

    def _get_misc_extractor(self) -> MiscExtractor:
        return self._get_extractor("_misc_extractor", MiscExtractor)

    def enable_result_tracking(self) -> IntrospectionResult:
        """Enable result tracking and return a new IntrospectionResult.

        Returns:
            IntrospectionResult instance for tracking
        """
        self._track_results = True
        self._current_result = IntrospectionResult()
        return self._current_result

    def get_result(self) -> Optional[IntrospectionResult]:
        """Get the current introspection result.

        Returns:
            IntrospectionResult if tracking is enabled, None otherwise
        """
        return self._current_result

    def _track_warning(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Track a warning if result tracking is enabled."""
        if self._track_results and self._current_result:
            self._current_result.add_warning(
                message, object_type, object_name, property_name, exception
            )

    def _track_error(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Track an error if result tracking is enabled."""
        if self._track_results and self._current_result:
            self._current_result.add_error(
                message, object_type, object_name, property_name, exception
            )

    def _track_object_status(
        self,
        object_type: str,
        object_name: str,
        schema: Optional[str] = None,
        captured: bool = True,
    ) -> ObjectCaptureStatus:
        """Track capture status for an object."""
        if not self._track_results or not self._current_result:
            return ObjectCaptureStatus(object_type, object_name, schema, captured)

        status = ObjectCaptureStatus(object_type, object_name, schema, captured)
        self._current_result.object_statuses.append(status)
        return status

    def _get_row_value(self, row: Dict[str, Any], key: str) -> Any:
        """Get value from row dictionary, handling both lowercase and uppercase keys."""
        return get_row_value(row, key)

    @staticmethod
    def _parse_pg_options(raw_options: Any) -> Dict[str, str]:
        """Parse PostgreSQL option arrays into dictionaries."""
        return parse_pg_options(raw_options)

    @staticmethod
    def _parse_json_array(raw_value: Any) -> List[Any]:
        """Parse a JSON array payload returned by vendor queries."""
        return parse_json_array(raw_value)

    @staticmethod
    def _strip_leading_comments(sql_text: str) -> str:
        """Remove leading comments/whitespace from SQL text."""
        return strip_leading_comments(sql_text)

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        """Best-effort conversion of metadata value to integer."""
        return to_int(value)

    def _ensure_native_connection(self) -> None:
        """Ensure a native provider connection exists without requesting metadata."""
        existing = getattr(self.provider, "connection", None)
        if existing is not None and getattr(existing, "closed", False) is not True:
            self.connection = existing
            return
        if not isinstance(self.provider, ConnectionProvider):
            raise AttributeError("Provider must implement ConnectionProvider interface")
        self.connection = self.provider.create_connection()

    def _ensure_metadata(self) -> None:
        """Ensure native providers have an active connection."""
        if self.connection is not None and getattr(self.connection, "closed", False) is not True:
            return
        self._ensure_native_connection()
        self.metadata = None

    def close(self) -> None:
        """Close connection if opened.

        Note: If the connection is the same as the provider's connection,
        we should NOT close it as the provider manages its own connection lifecycle.
        """
        if self.connection:
            # Check if this is the provider's connection - if so, don't close it
            # The provider manages its own connection lifecycle
            is_provider_connection = (
                hasattr(self.provider, "connection") and self.provider.connection is self.connection
            )

            if not is_provider_connection:
                # This is a connection we created ourselves, safe to close
                try:
                    self.connection.close()
                except Exception as e:
                    self.log.warning(f"Error closing connection: {e}")
            else:
                # This is the provider's connection - just clear our reference
                self.log.debug("Not closing connection as it belongs to the provider")

            # Always clear our references
            self.connection = None
            self.metadata = None

    def get_tables(
        self, schema: str, include_views: bool = False, table_pattern: str = "%"
    ) -> List[Table]:
        """
        Get all tables in the specified schema.

        Args:
            schema: Schema name
            include_views: Whether to include views as tables
            table_pattern: Table name pattern (% = wildcard)

        Returns:
            List of Table objects with full metadata (columns and constraints)

        Example:
            >>> tables = introspector.get_tables("public")
            >>> users_table = next(t for t in tables if t.name == "users")
            >>> print(f"Columns: {[c.name for c in users_table.columns]}")
        """
        # Delegate to table extractor
        return self._get_table_extractor().get_tables(schema, include_views, table_pattern)

    def _get_columns(self, schema: str, table: str) -> List[SqlColumn]:
        """
        Get all columns for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlColumn objects with full metadata
        """
        # Delegate to column extractor
        return self._get_column_extractor().get_columns(schema, table)

    def _get_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get all constraints for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects (PK, FK, Unique)
        """
        # Delegate to constraint extractor
        return self._get_constraint_extractor().get_constraints(schema, table)

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """
        Get all indexes for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of Index objects

        Example:
            >>> indexes = introspector.get_indexes("public", "users")
            >>> for idx in indexes:
            ...     print(f"{idx.name}: {idx.columns}")
        """
        # Delegate to index extractor
        return self._get_index_extractor().get_indexes(schema, table)

    def get_all_indexes(self, schema: str) -> List[Index]:
        """
        Get all indexes for an entire schema in a single bulk query.

        Delegates to IndexExtractor.get_all_indexes. Returns an empty list
        if the dialect does not support bulk index retrieval.

        Args:
            schema: Schema name

        Returns:
            List of Index objects for the entire schema, or [] if the dialect
            does not support bulk retrieval.
        """
        return self._get_index_extractor().get_all_indexes(schema)

    def get_check_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get check constraints for a table using vendor-specific queries.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects with CHECK type

        Example:
            >>> constraints = introspector.get_check_constraints("public", "users")
            >>> for c in constraints:
            ...     print(f"{c.name}: {c.check_expression}")
        """
        # Delegate to constraint extractor
        return self._get_constraint_extractor().get_check_constraints(schema, table)

    def introspect_schema_basic(self, schema: str) -> Dict[str, Any]:
        """
        Introspect entire schema and return basic metadata.

        This is a simpler operation that extracts core database objects
        from the specified schema with structural metadata.

        Args:
            schema: Schema name

        Returns:
            Dictionary containing:
            {
                "schema": str,
                "tables": List[Table],
                "indexes": Dict[table_name, List[Index]],
                "table_count": int,
                "total_columns": int,
                "total_indexes": int
            }

        Example:
            >>> result = introspector.introspect_schema("public")
            >>> print(f"Found {result['table_count']} tables")
            >>> print(f"Total columns: {result['total_columns']}")
        """
        result: Dict[str, Any] = {
            "schema": schema,
            "tables": [],
            "indexes": {},
            "table_count": 0,
            "total_columns": 0,
            "total_indexes": 0,
        }

        self.log.info(f"Starting full schema introspection: {schema}")

        try:
            # Get all tables with full metadata
            tables = self.get_tables(schema, include_views=False)
            result["tables"] = tables
            result["table_count"] = len(tables)

            # Get indexes for each table
            for table in tables:
                total_cols: int = result["total_columns"]
                result["total_columns"] = total_cols + len(table.columns)

                # Get indexes
                indexes = self.get_indexes(schema, table.name)
                result["indexes"][table.name] = indexes
                total_idx: int = result["total_indexes"]
                result["total_indexes"] = total_idx + len(indexes)

            self.log.info(
                f"Introspection complete: {result['table_count']} tables, "
                f"{result['total_columns']} columns, "
                f"{result['total_indexes']} indexes"
            )

        except Exception as e:
            self.log.error(f"Error introspecting schema {schema}: {e}")
            raise

        return result

    def get_database_info(self) -> Dict[str, str]:
        """
        Get database product information.

        Returns:
            Dictionary with database metadata:
            {
                "product_name": str,
                "product_version": str,
                "driver_name": str,
                "driver_version": str
            }
        """
        try:
            product_name = str(getattr(self.provider, "canonical_dialect_key", "") or self.dialect)
            product_version = ""
            get_database_version = getattr(self.provider, "get_database_version", None)
            if callable(get_database_version):
                self._ensure_metadata()
                product_version = str(get_database_version())
            driver_name = get_provider_driver_display(self.provider) or ""
            return {
                "product_name": product_name,
                "product_version": product_version,
                "driver_name": driver_name,
                "driver_version": "",
            }
        except Exception as e:
            self.log.error(f"Error getting database info: {e}")
            return {}

    def enrich_columns_with_computed(
        self, schema: str, table: str, columns: List[SqlColumn]
    ) -> None:
        """Delegate to :func:`core.introspection._column_enricher.enrich_columns_with_computed`.

        Kept as a method so existing callers (and the source-inspection tests
        in ``test_schema_introspector_inline_imports``) continue to work.
        """
        from core.introspection._column_enricher import enrich_columns_with_computed as _impl

        _impl(self, schema, table, columns)

    def enrich_columns_with_identity(
        self, schema: str, table: str, columns: List[SqlColumn]
    ) -> None:
        """Delegate to :func:`core.introspection._column_enricher.enrich_columns_with_identity`."""
        from core.introspection._column_enricher import enrich_columns_with_identity as _impl

        _impl(self, schema, table, columns)

    # -- Vendor property application — delegated to VendorPropertyApplier (SRP-02) --
    # ``_apply_vendor_table_properties_<dialect>`` shims dispatch to the
    # plugin's quirks ``apply_vendor_table_properties`` (Wave H.1). Kept
    # so that existing test calls and any external caller relying on the
    # per-dialect entry points continue to work.

    def _apply_vendor_table_properties(self, schema: str, table_name: str, table: "Table") -> None:
        """Enrich table objects with vendor-specific properties.

        Delegates to VendorPropertyApplier (SRP-02).
        """
        # Sync applier state in case dialect/vendor_queries changed after __init__
        self._vendor_property_applier.dialect = self.dialect
        self._vendor_property_applier.vendor_queries = self.vendor_queries
        self._vendor_property_applier.log = self.log
        self._vendor_property_applier.apply(
            schema, table_name, table, self.connection, self.provider.query_executor
        )

    def enrich_table_with_partition_scheme(
        self, schema: str, table_name: str, table: "Table"
    ) -> None:
        """Delegate to :func:`core.introspection._partition_enricher.enrich_table_with_partition_scheme`.

        Kept as a method so existing callers (and the source-inspection tests
        in ``test_schema_introspector_inline_imports``) continue to work.
        """
        from core.introspection._partition_enricher import (
            enrich_table_with_partition_scheme as _impl,
        )

        _impl(self, schema, table_name, table)

    def get_table_partitions(self, schema: str, table: str) -> List[Any]:
        """Delegate to :func:`core.introspection._partition_enricher.get_table_partitions`."""
        from core.introspection._partition_enricher import get_table_partitions as _impl

        return _impl(self, schema, table)

    def get_sequences(self, schema: str) -> List[Sequence]:
        """
        Get sequences in a schema using vendor-specific queries.

        Args:
            schema: Schema name

        Returns:
            List of Sequence objects

        Example:
            >>> sequences = introspector.get_sequences("public")
            >>> for seq in sequences:
            ...     print(f"{seq.name}: start={seq.start_with}, increment={seq.increment_by}")
        """
        # Delegate to sequence extractor
        return self._get_sequence_extractor().get_sequences(schema)

    def get_views(self, schema: str) -> List[View]:
        """
        Get views in a schema using vendor-specific queries.

        Args:
            schema: Schema name

        Returns:
            List of View objects with their definitions

        Example:
            >>> views = introspector.get_views("public")
            >>> for view in views:
            ...     print(f"{view.name}: {view.query[:50]}...")
        """
        # Delegate to view extractor
        return self._get_view_extractor().get_views(schema)

    def get_materialized_views(self, schema: str) -> List[View]:
        """
        Get materialized views in a schema using vendor-specific queries.

        Materialized views are supported by PostgreSQL (9.3+) and Oracle.

        Args:
            schema: Schema name

        Returns:
            List of View objects with materialized=True

        Example:
            >>> mviews = introspector.get_materialized_views("public")
            >>> for mview in mviews:
            ...     print(f"{mview.name}: populated={mview.is_populated}")
        """
        # Short-circuit on capability flag — avoids opening a connection
        # just to construct an extractor that would return [].
        if not self.vendor_queries or not self.vendor_queries.supports_materialized_views():
            return []
        return self._get_view_extractor().get_materialized_views(schema)

    def get_triggers(self, schema: str, table: Optional[str] = None) -> List[Trigger]:
        """
        Get triggers in a schema (optionally filtered by table).

        Args:
            schema: Schema name
            table: Optional table name to filter triggers

        Returns:
            List of Trigger objects

        Example:
            >>> triggers = introspector.get_triggers("public", "users")
            >>> for trigger in triggers:
            ...     print(f"{trigger.name}: {trigger.timing} {trigger.event_str}")
        """
        # Delegate to trigger extractor
        return self._get_trigger_extractor().get_triggers(schema, table)

    def get_events(self, schema: str) -> List[Any]:
        """
        Get scheduled events in a schema (MySQL only).

        Args:
            schema: Schema name

        Returns:
            List of Event objects

        Example:
            >>> events = introspector.get_events("mydb")
            >>> for event in events:
            ...     print(f"{event.name}: {event.schedule}")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_events():
            return []
        return self._get_misc_extractor().get_events(schema)

    def get_procedures(self, schema: str) -> List[Any]:
        """
        Get stored procedures in a schema.

        Args:
            schema: Schema name

        Returns:
            List of Procedure objects

        Example:
            >>> procedures = introspector.get_procedures("public")
            >>> for proc in procedures:
            ...     print(f"{proc.name}: {len(proc.parameters)} parameters")
        """
        # Delegate to procedure extractor
        return self._get_procedure_extractor().get_procedures(schema)

    def get_functions(self, schema: str) -> List[Any]:
        """
        Get functions in a schema.

        Args:
            schema: Schema name

        Returns:
            List of Procedure objects (with is_function=True)

        Example:
            >>> functions = introspector.get_functions("public")
            >>> for func in functions:
            ...     print(f"{func.name}: returns {func.return_type}")
        """
        # Delegate to procedure extractor, passing get_user_defined_types for DB2 filtering
        return self._get_procedure_extractor().get_functions(
            schema, get_user_defined_types_fn=self.get_user_defined_types
        )

    def get_packages(self, schema: str) -> List[Any]:
        """
        Get packages (Oracle) or modules (DB2) in a schema.

        Oracle packages are containers for procedures, functions, and variables.
        DB2 modules serve a similar purpose.

        Args:
            schema: Schema name

        Returns:
            List of Package objects

        Example:
            >>> packages = introspector.get_packages("HR")
            >>> for pkg in packages:
            ...     print(f"{pkg.name} ({pkg.language})")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_packages():
            return []
        # Delegate to misc extractor, sharing Oracle package specs cache
        misc_extractor = self._get_misc_extractor()
        # Share the Oracle package specs cache with MiscExtractor if both have it
        # (guard needed: self._oracle_package_specs is only on SchemaIntrospector, not BaseIntrospector)
        if hasattr(self, "_oracle_package_specs") and hasattr(
            misc_extractor, "_oracle_package_specs"
        ):
            misc_extractor._oracle_package_specs = self._oracle_package_specs
        return misc_extractor.get_packages(schema)

    def get_synonyms(self, schema: str) -> List[Any]:
        """
        Get synonyms in a schema.

        Args:
            schema: Schema name

        Returns:
            List of Synonym objects

        Example:
            >>> synonyms = introspector.get_synonyms("dbo")
            >>> for synonym in synonyms:
            ...     print(f"{synonym.name} -> {synonym.target_full_name}")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_synonyms():
            return []
        return self._get_misc_extractor().get_synonyms(schema)

    def get_user_defined_types(self, schema: str) -> List[Any]:
        """
        Get user-defined types in a schema.

        Uses plugin-owned vendor queries for detailed information like enum
        values and composite type attributes.

        Args:
            schema: Schema name

        Returns:
            List of UserDefinedType objects

        Example:
            >>> types = introspector.get_user_defined_types("public")
            >>> for udt in types:
            ...     if udt.is_enum:
            ...         print(f"ENUM {udt.name}: {', '.join(udt.enum_values)}")
            ...     elif udt.is_composite:
            ...         print(f"COMPOSITE {udt.name}: {len(udt.attributes)} attributes")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_user_defined_types():
            return []
        return self._get_misc_extractor().get_user_defined_types(
            schema, get_tables_fn=self.get_tables
        )

    def get_extensions(self) -> List[Any]:
        """
        Get installed database extensions (PostgreSQL-specific).

        Args:
            None (extensions are database-wide in PostgreSQL)

        Returns:
            List of Extension objects

        Example:
            >>> extensions = introspector.get_extensions()
            >>> for ext in extensions:
            ...     print(f"{ext.name} v{ext.version}: {ext.description}")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_extensions():
            return []
        return self._get_misc_extractor().get_extensions()

    def get_foreign_data_wrappers(self) -> List[Any]:
        """
        Get foreign data wrappers (PostgreSQL-specific).
        """
        if not self.vendor_queries or not self.vendor_queries.supports_foreign_data_wrappers():
            return []
        return self._get_misc_extractor().get_foreign_data_wrappers()

    def get_foreign_servers(self) -> List[Any]:
        """
        Get foreign servers (PostgreSQL-specific).
        """
        if not self.vendor_queries or not self.vendor_queries.supports_foreign_servers():
            return []
        return self._get_misc_extractor().get_foreign_servers()

    def get_database_links(self, schema: str) -> List[Any]:
        """
        Get database links in a schema (Oracle-specific).

        Args:
            schema: Schema name

        Returns:
            List of DatabaseLink objects

        Example:
            >>> db_links = introspector.get_database_links("myschema")
            >>> for link in db_links:
            ...     print(f"{link.name} -> {link.host}")
        """
        if not self.vendor_queries or not self.vendor_queries.supports_database_links():
            return []
        return self._get_misc_extractor().get_database_links(schema)

    def get_linked_servers(self) -> List[Any]:
        """
        Get linked servers (SQL Server-specific).

        Returns:
            List of LinkedServer objects
        """
        if not self.vendor_queries or not self.vendor_queries.supports_linked_servers():
            return []
        return self._get_misc_extractor().get_linked_servers()

    def get_modules(self, schema: str) -> List[Any]:
        """
        Get modules in a schema (DB2-specific).

        Args:
            schema: Schema name

        Returns:
            List of Module objects
        """
        if not self.vendor_queries or not self.vendor_queries.supports_modules():
            return []
        return self._get_misc_extractor().get_modules(schema)

    def introspect_schema(self, schema: str, **kwargs: Any) -> Dict[str, Any]:
        """Delegate to :func:`core.introspection._schema_orchestrator.introspect_schema`.

        Kept as a method on ``SchemaIntrospector`` so existing callers and the
        public-API surface keep working. The body of the orchestration lives
        in its own module to keep this class focused on per-kind ``get_X``
        entry points and extractor lifecycle.
        """
        from core.introspection._schema_orchestrator import introspect_schema as _impl

        return _impl(self, schema, **kwargs)

    def __enter__(self) -> "BaseIntrospector":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - close connection."""
        self.close()
