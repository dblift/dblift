"""Apply vendor-specific table properties to introspected ``Table`` objects.

Extracted from :class:`core.introspection.schema_introspector.SchemaIntrospector`
to keep that orchestrator focused on flow control. The actual per-dialect
mapping (which catalog columns enrich which ``Table`` attributes) lives
on each plugin's quirks via
:meth:`db.base_quirks.BaseQuirks.apply_vendor_table_properties`; this
class only owns the orchestration: run ``get_table_properties_query``,
hand the first row to the dialect's quirks hook.

Wave H.1 ménage: the four ``_apply_<dialect>_properties`` static
methods + the ``_HANDLERS`` dispatch dict that used to live here
moved to the per-plugin quirks files (sqlserver, db2, oracle, mysql).
"""

from __future__ import annotations

from typing import Any, Optional


class VendorPropertyApplier:
    """Run the vendor table-properties query and hand the row to quirks.

    Holds no dialect knowledge of its own — every dialect-specific bit
    is delegated to ``ProviderRegistry.get_quirks(dialect)
    .apply_vendor_table_properties(table, row)``.
    """

    def __init__(self, dialect: Optional[str], vendor_queries: Any, log: Any) -> None:
        """Initialize the applier.

        Args:
            dialect: Lowercase database dialect string (e.g. "oracle", "mysql").
            vendor_queries: Vendor queries object (may be None).
            log: Logger instance.
        """
        self.dialect = dialect
        self.vendor_queries = vendor_queries
        self.log = log

    def apply(
        self, schema: str, table_name: str, table: Any, connection: Any, query_executor: Any
    ) -> None:
        """Apply vendor-specific table properties to a table object.

        Args:
            schema: Schema name
            table_name: Table name
            table: Table object to enrich
            connection: Active database connection
            query_executor: Query executor for running vendor queries
        """
        if not self.vendor_queries:
            return

        # Resolve dialect quirks lazily so a None / unknown dialect just
        # returns a vanilla ``BaseQuirks`` whose
        # ``apply_vendor_table_properties`` is a no-op — no special-casing
        # required here.
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")

        try:
            query, params = self.vendor_queries.get_table_properties_query(schema, table_name)
            results = query_executor.execute_query(connection, query, params)
            if results:
                quirks.apply_vendor_table_properties(table, results[0])
        except Exception as e:
            self.log.debug(f"Could not get vendor table properties for {schema}.{table_name}: {e}")
