"""Table extraction from plugin-owned vendor metadata queries."""

import fnmatch
import logging
from typing import Any, List, Optional, Set

from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.table import Table

logger = logging.getLogger(__name__)


class TableExtractor(BaseExtractor):
    """Extract table metadata from plugin-owned vendor metadata queries."""

    def __init__(
        self,
        provider: Any,
        connection: Any = None,
        metadata: Any = None,
        vendor_queries: Any = None,
        dialect: str = "unknown",
        log: Any = None,
        result_tracker: Any = None,
        column_extractor: Any = None,
        constraint_extractor: Any = None,
    ) -> None:
        """
        Initialize the table extractor.

        Args:
            provider: Database provider
            connection: Optional database connection
            metadata: Unused legacy slot retained for extractor constructor compatibility
            vendor_queries: Optional vendor-specific queries instance
            dialect: Database dialect name
            log: Optional logger instance
            result_tracker: Optional result tracking instance
            column_extractor: Optional column extractor instance
            constraint_extractor: Optional constraint extractor instance
        """
        super().__init__(
            provider, connection, metadata, vendor_queries, dialect, log, result_tracker
        )
        self.column_extractor = column_extractor
        self.constraint_extractor = constraint_extractor
        self._dblift_internal_names: Optional[Set[str]] = None

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
        """
        self.ensure_metadata()
        if not self.vendor_queries:
            raise RuntimeError("Vendor metadata queries not available")
        query_result = self.vendor_queries.get_tables_query(schema)
        if query_result is None:
            raise RuntimeError(f"Table metadata query not available for {self.dialect}")

        # Determine table types to fetch
        types = ["TABLE"]
        if include_views:
            types.append("VIEW")

        tables = []

        try:
            self.log.debug(f"Getting tables from vendor queries: schema={schema}, types={types}")
            query, params = query_result
            rows = self.provider.query_executor.execute_query(self.connection, query, params)

            for row in rows:
                table_name = self.get_row_value(row, "table_name")
                if not table_name:
                    continue
                table_name = str(table_name)

                # Apply table_pattern filter (SQL % wildcard → fnmatch * wildcard)
                if table_pattern != "%" and not fnmatch.fnmatch(
                    table_name.lower(), table_pattern.lower().replace("%", "*")
                ):
                    continue

                # Filter out internal/system tables
                if self._should_skip_table(table_name, schema, set()):
                    continue

                table_schema = self.get_row_value(row, "table_schema") or self.get_row_value(
                    row, "table_schem"
                )
                if table_schema and not self._verify_schema_match(
                    str(table_schema), schema, table_name
                ):
                    continue

                table_type = self.get_row_value(row, "table_type")
                is_temporary = self._coerce_bool(
                    self.get_row_value(row, "is_temporary")
                ) or self._is_temporary_table(self.to_python_string(table_type), table_name)
                remarks = self.get_row_value(row, "comment") or self.get_row_value(row, "remarks")

                self.log.debug(f"Introspecting table: {schema}.{table_name}")

                # Create table object
                table = Table(
                    name=table_name,
                    schema=schema,
                    dialect=self.dialect,
                    comment=str(remarks) if remarks else None,
                    temporary=is_temporary,
                )

                # Track table capture status
                table_status = self.track_object_status("table", table_name, schema)

                # Get columns
                try:
                    if self.column_extractor:
                        table.columns = self.column_extractor.get_columns(schema, table_name)
                    else:
                        # Fallback: import from schema_introspector (temporary bridge)
                        from core.introspection.schema_introspector import SchemaIntrospector

                        temp_introspector = SchemaIntrospector(
                            self.provider, self.log, use_vendor_queries=False
                        )
                        temp_introspector.dialect = self.dialect
                        temp_introspector.connection = self.connection
                        temp_introspector.metadata = self.metadata
                        temp_introspector.vendor_queries = self.vendor_queries
                        table.columns = temp_introspector._get_columns(schema, table_name)

                    if table_status:
                        table_status.add_property_status("columns", True)
                except Exception as e:
                    if table_status:
                        table_status.add_property_status("columns", False)
                    self.track_error(
                        f"Failed to get columns for table {schema}.{table_name}: {e}",
                        object_type="table",
                        object_name=table_name,
                        property_name="columns",
                        exception=e,
                    )
                    table.columns = []

                # Get constraints
                try:
                    if self.constraint_extractor:
                        table.constraints = self.constraint_extractor.get_constraints(
                            schema, table_name
                        )
                    else:
                        # Fallback: import from schema_introspector (temporary bridge)
                        from core.introspection.schema_introspector import SchemaIntrospector

                        temp_introspector = SchemaIntrospector(
                            self.provider, self.log, use_vendor_queries=False
                        )
                        temp_introspector.dialect = self.dialect
                        temp_introspector.connection = self.connection
                        temp_introspector.metadata = self.metadata
                        temp_introspector.vendor_queries = self.vendor_queries
                        table.constraints = temp_introspector._get_constraints(schema, table_name)

                    if table_status:
                        table_status.add_property_status("constraints", True)
                except Exception as e:
                    if table_status:
                        table_status.add_property_status("constraints", False)
                    self.track_warning(
                        f"Failed to get constraints for table {schema}.{table_name}: {e}",
                        object_type="table",
                        object_name=table_name,
                        property_name="constraints",
                        exception=e,
                    )
                    table.constraints = []

                self._enrich_table(schema, table_name, table)

                tables.append(table)

            if include_views:
                tables.extend(self._get_view_tables(schema, table_pattern))

        except Exception as e:
            logger.error(f"Error getting tables for schema {schema}: {e}")
            self.log.error(f"Error getting tables for schema {schema}: {e}")
            self.track_error(
                f"Error getting tables for schema {schema}: {e}",
                object_type="schema",
                object_name=schema,
                exception=e,
            )
            raise

        # Supplement with partitioned tables (PostgreSQL-specific)
        tables = self._supplement_partitioned_tables(schema, tables)

        # Enrich all tables with partition scheme information
        for table in tables:
            try:
                self._enrich_partition_scheme(schema, table.name, table)
            except Exception as e:
                self.log.debug(
                    f"Could not get partition scheme for table {schema}.{table.name}: {e}"
                )

        self.log.debug(f"Introspected {len(tables)} tables from schema {schema}")

        return tables

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().upper() in {"1", "Y", "YES", "TRUE", "T"}
        return bool(value)

    def _get_view_tables(self, schema: str, table_pattern: str = "%") -> List[Table]:
        """Return views as lightweight Table objects when requested."""
        query_result = self.vendor_queries.get_view_names_query(schema)
        if query_result is None:
            return []

        query, params = query_result
        rows = self.provider.query_executor.execute_query(self.connection, query, params)
        views: List[Table] = []
        for row in rows:
            view_name = self.get_row_value(row, "view_name")
            if not view_name:
                continue
            view_name = str(view_name)
            if table_pattern != "%" and not fnmatch.fnmatch(
                view_name.lower(), table_pattern.lower().replace("%", "*")
            ):
                continue
            view = Table(name=view_name, schema=schema, dialect=self.dialect)
            if self.column_extractor:
                try:
                    view.columns = self.column_extractor.get_columns(schema, view_name)
                except Exception:
                    view.columns = []
            views.append(view)
        return views

    # Helper methods for table extraction

    def _should_preload_materialized_views(self, schema: str) -> bool:
        """Whether the extractor needs to preload MV names to filter them out.

        Driven by the quirks-declared
        :attr:`BaseQuirks.materialized_view_support_table_prefixes`
        tuple — Oracle is the only dialect with a non-empty tuple.
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return bool(
            quirks.materialized_view_support_table_prefixes
            and self.vendor_queries
            and self.vendor_queries.supports_materialized_views()
        )

    def _preload_materialized_view_names(self, schema: str) -> Set[str]:
        """Preload materialized view names for filtering."""
        try:
            # Import here to avoid circular dependency
            from core.introspection.schema_introspector import SchemaIntrospector

            temp_introspector = SchemaIntrospector(
                self.provider, self.log, use_vendor_queries=False
            )
            temp_introspector.dialect = self.dialect
            temp_introspector.connection = self.connection
            temp_introspector.metadata = self.metadata
            temp_introspector.vendor_queries = self.vendor_queries
            views = temp_introspector.get_materialized_views(schema)
            return {view.name.upper() for view in views}
        except Exception as e:
            self.log.debug(f"Could not preload materialized view names for {schema}: {e}")
            self.track_warning(
                f"Could not preload materialized view names: {e}",
                object_type="materialized_view",
                exception=e,
            )
            return set()

    def _get_dblift_internal_names(self) -> Set[str]:
        """Build the set of dblift-internal table names to hide from introspection.

        BUG-03B: names are config-overridable (``history_table`` /
        ``snapshot_table`` in ``DatabaseConfig``, ENV ``DBLIFT_HISTORY_TABLE`` /
        ``DBLIFT_SNAPSHOT_TABLE``). Hardcoded literals broke the filter when
        the user overrode the names. Default values come from the canonical
        constants — configured history / snapshot names, provider lock-table
        metadata, and ``DBLIFT_SCHEMA_SNAPSHOTS_TABLE`` from ``core.constants``.

        Each name is normalized via ``get_normalized_object_name`` so the
        comparison matches the case the database actually stores
        (UPPERCASE on Oracle/DB2, lowercase elsewhere). ``SCHEMA_VERSION``
        is retained as the Flyway-compat legacy history name.

        Cached on first use; subsequent calls return the cached set.
        """
        if self._dblift_internal_names is not None:
            return self._dblift_internal_names

        from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE
        from db.object_naming import get_normalized_object_name

        db = getattr(getattr(self.provider, "config", None), "database", None)
        history_raw = getattr(db, "history_table", None)
        snapshot_raw = getattr(db, "snapshot_table", None)
        history = history_raw if isinstance(history_raw, str) else "dblift_schema_history"
        snapshot = snapshot_raw if isinstance(snapshot_raw, str) else DBLIFT_SCHEMA_SNAPSHOTS_TABLE
        lock = getattr(self.provider, "MIGRATION_LOCK_TABLE", "dblift_migration_lock")
        flyway_legacy = "schema_version"

        dialect = self.dialect or ""
        self._dblift_internal_names = {
            get_normalized_object_name(history, dialect),
            get_normalized_object_name(snapshot, dialect),
            get_normalized_object_name(lock, dialect),
            get_normalized_object_name(flyway_legacy, dialect),
        }
        return self._dblift_internal_names

    def _should_skip_table(
        self, table_name: str, schema: str, materialized_view_names: Set[str]
    ) -> bool:
        """Check if a table should be skipped.

        Filters dblift-internal tables (config-overridable names) and
        engine-internal materialized-view support objects whose prefixes
        the plugin's quirks declares via
        :attr:`BaseQuirks.materialized_view_support_table_prefixes`.
        """
        from db.object_naming import get_normalized_object_name
        from db.provider_registry import ProviderRegistry

        normalized = get_normalized_object_name(table_name, self.dialect or "")
        if normalized in self._get_dblift_internal_names():
            self.log.debug(
                f"Skipping internal dblift table during introspection: {schema}.{table_name}"
            )
            return True

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        mv_prefixes = quirks.materialized_view_support_table_prefixes
        if mv_prefixes:
            upper_name = table_name.upper()
            if upper_name.startswith(mv_prefixes):
                self.log.debug(f"Skipping materialized-view support object: {table_name}")
                return True
            if materialized_view_names and upper_name in materialized_view_names:
                self.log.debug(f"Skipping materialized view from table list: {table_name}")
                return True

        return False

    def _verify_schema_match(
        self, table_schema: Optional[str], expected_schema: str, table_name: str
    ) -> bool:
        """Verify that table schema matches expected schema (case-insensitive)."""
        if table_schema and table_schema.upper() != expected_schema.upper():
            self.log.debug(
                f"Skipping table {table_name} from different schema: {table_schema} != {expected_schema}"
            )
            return False
        return True

    def _is_temporary_table(self, table_type: Optional[str], table_name: str) -> bool:
        """Detect if a table is temporary based on TABLE_TYPE."""
        if not table_type:
            return False

        table_type_upper = table_type.upper()
        is_temporary = any(
            temp_type in table_type_upper
            for temp_type in [
                "TEMPORARY",
                "TEMP",
                "GLOBAL TEMPORARY",
                "LOCAL TEMPORARY",
            ]
        )

        if is_temporary and self.log:
            self.log.debug(f"Detected temporary table: {table_name} (type: {table_type})")

        return is_temporary

    def _enrich_table(self, schema: str, table_name: str, table: Table) -> None:
        """Enrich table with additional metadata."""
        from db.provider_registry import ProviderRegistry

        # Enrich columns with computed/generated metadata
        if self.vendor_queries and self.vendor_queries.supports_computed_columns():
            self._enrich_computed_columns(schema, table_name, table.columns)

        # Vendor-specific table property enrichment
        self._apply_vendor_table_properties(schema, table_name, table)

        # Dialect-specific extra enrichment (PostgreSQL: row security +
        # inheritance + RLS policies). Default: no-op.
        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        quirks.enrich_table_extra(self, schema, table_name, table)

    def _enrich_computed_columns(self, schema: str, table_name: str, columns: List[Any]) -> None:
        """Enrich columns with computed/generated metadata."""
        # Import here to avoid circular dependency
        from core.introspection.schema_introspector import SchemaIntrospector

        temp_introspector = SchemaIntrospector(self.provider, self.log, use_vendor_queries=False)
        temp_introspector.dialect = self.dialect
        temp_introspector.connection = self.connection
        temp_introspector.vendor_queries = self.vendor_queries
        temp_introspector.enrich_columns_with_computed(schema, table_name, columns)

    def _apply_vendor_table_properties(self, schema: str, table_name: str, table: Table) -> None:
        """Apply vendor-specific table properties."""
        # Import here to avoid circular dependency
        from core.introspection.schema_introspector import SchemaIntrospector

        temp_introspector = SchemaIntrospector(self.provider, self.log, use_vendor_queries=False)
        temp_introspector.dialect = self.dialect
        temp_introspector.connection = self.connection
        temp_introspector.vendor_queries = self.vendor_queries
        temp_introspector._apply_vendor_table_properties(schema, table_name, table)

    def _supplement_partitioned_tables(
        self, schema: str, existing_tables: List[Table]
    ) -> List[Table]:
        """Append dialect-specific tables missing from the generic table list.

        Delegates to the plugin's quirks
        :meth:`BaseQuirks.supplement_table_list`; the default
        implementation returns *existing_tables* unchanged.
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return quirks.supplement_table_list(self, schema, existing_tables)

    def _enrich_partition_scheme(self, schema: str, table_name: str, table: Table) -> None:
        """Enrich table with partition scheme information."""
        # Import here to avoid circular dependency
        from core.introspection.schema_introspector import SchemaIntrospector

        temp_introspector = SchemaIntrospector(self.provider, self.log, use_vendor_queries=False)
        temp_introspector.dialect = self.dialect
        temp_introspector.connection = self.connection
        temp_introspector.vendor_queries = self.vendor_queries
        temp_introspector.enrich_table_with_partition_scheme(schema, table_name, table)
