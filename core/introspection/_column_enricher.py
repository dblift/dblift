"""Column enrichment helpers for ``SchemaIntrospector``.

Extracted from :mod:`core.introspection.schema_introspector` to keep the
orchestrator focused. ``SchemaIntrospector`` keeps thin wrapper methods
(``enrich_columns_with_computed``, ``enrich_columns_with_identity``)
that delegate here, preserving the public surface used by tests and
callers.

The two helpers take the introspector instance as their first parameter
(``si``) instead of being bound methods so the dependency on
``self.vendor_queries`` / ``self.provider`` / ``self.connection`` /
``self.dialect`` / ``self.log`` and the helpers ``self._get_row_value``
/ ``self._ensure_metadata`` is explicit.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from core.introspection.schema_introspector import SchemaIntrospector
    from core.sql_model.base import SqlColumn


def enrich_columns_with_computed(
    si: "SchemaIntrospector", schema: str, table: str, columns: List["SqlColumn"]
) -> None:
    """Enrich *columns* with computed/generated column metadata.

    The base column extractor loads the coarse computed flag from the
    plugin's column query. This pass enriches matching columns with
    expression/storage details from the plugin's computed-column query.
    """
    # Columns may already have is_computed set from the plugin's column query.
    # This method adds detailed metadata (expression, stored flag).

    # Try to add detailed metadata from vendor queries if available
    if not si.vendor_queries or not si.vendor_queries.supports_computed_columns():
        si.log.debug(
            "enrich_columns_with_computed: vendor queries not available or "
            "don't support computed columns"
        )
        return

    # Ensure we have a connection without requesting metadata on native providers.
    if getattr(si.provider, "provider_transport", "native") == "native":
        si._ensure_native_connection()
    else:
        si._ensure_metadata()

    try:
        sql, params = si.vendor_queries.get_computed_columns_query(schema, table)
        if not sql:
            si.log.debug(
                f"enrich_columns_with_computed: no SQL query returned for {schema}.{table}"
            )
            return

        si.log.debug(
            f"enrich_columns_with_computed: querying computed columns for "
            f"{schema}.{table} with params {params}"
        )

        results = si.provider.query_executor.execute_query(si.connection, sql, params)

        si.log.debug(
            f"enrich_columns_with_computed: query returned {len(results)} rows "
            f"for {schema}.{table}"
        )

        # Create a mapping of column name to computed metadata
        computed_map = {}
        for row in results:
            si.log.debug(f"enrich_columns_with_computed: processing row: {row}")
            column_name = (
                si._get_row_value(row, "column_name")
                or row.get("COLUMN_NAME")
                or row.get("column_name")
            )
            if column_name:
                # Get computation expression - try multiple column name variations.
                # DB2 TEXT column contains full definition like
                # "GENERATED ALWAYS AS (price * quantity)" — extract just the expression part.
                computation_expr = (
                    si._get_row_value(row, "computation_expression")
                    or row.get("COMPUTATION_EXPRESSION")
                    or row.get("computation_expression")
                    or si._get_row_value(row, "text")
                    or row.get("TEXT")
                    or row.get("text")
                )
                # Vendor-specific wrapper extraction (DB2 unwraps
                # ``GENERATED ALWAYS AS (...)`` from SYSCAT.COLUMNS.TEXT;
                # other dialects return the expression as-is).
                if computation_expr:
                    from db.provider_registry import ProviderRegistry

                    quirks = ProviderRegistry.get_quirks(si.dialect or "")
                    computation_expr = quirks.extract_computed_column_expression(computation_expr)
                # Convert to string if it's not already (handles CLOB objects)
                if computation_expr is not None:
                    if not isinstance(computation_expr, str):
                        computation_expr = str(computation_expr)
                    # Strip whitespace and check if not empty
                    computation_expr = computation_expr.strip()
                    # DB2: Handle empty strings - if expression is empty, skip this column.
                    # Empty expression means the column might not actually be computed
                    if not computation_expr:
                        si.log.debug(
                            f"DB2 computed column {column_name} has empty expression, "
                            "skipping enrichment"
                        )
                        continue
                # Only add to map if expression is not None and not empty
                if computation_expr:
                    computed_map[column_name.upper()] = {
                        "computation_expression": computation_expr,
                        "is_stored": (
                            si._get_row_value(row, "is_stored")
                            or row.get("IS_STORED")
                            or row.get("is_stored")
                        ),
                    }
                    si.log.debug(
                        f"enrich_columns_with_computed: added computed column "
                        f"{column_name} with expression: {computation_expr}"
                    )
                else:
                    # Log when we have a computed column but couldn't extract expression
                    si.log.debug(
                        f"Could not extract computation expression for column "
                        f"{column_name} from row: {row}"
                    )

        si.log.debug(
            f"enrich_columns_with_computed: computed_map has {len(computed_map)} "
            f"entries: {list(computed_map.keys())}"
        )
        si.log.debug(
            f"enrich_columns_with_computed: checking {len(columns)} columns: "
            f"{[col.name for col in columns]}"
        )

        # Enrich matching columns with detailed metadata
        for column in columns:
            computed_data = computed_map.get(column.name.upper())
            si.log.debug(
                f"enrich_columns_with_computed: column {column.name} "
                f"(upper: {column.name.upper()}) -> computed_data: "
                f"{computed_data is not None}"
            )
            if computed_data:
                # Mark as computed (may already be marked from the column query)
                column.is_computed = True
                # Add detailed metadata using SQL Model attribute names
                column.computed_expression = computed_data["computation_expression"]
                # Convert is_stored boolean to computed_stored.
                # Handle both string ('Y'/'N') and boolean values
                is_stored_value = computed_data["is_stored"]
                if is_stored_value is not None:
                    if isinstance(is_stored_value, str):
                        # String values: 'Y', 'YES', 'TRUE' -> True, else False
                        column.computed_stored = is_stored_value.upper() in (
                            "Y",
                            "YES",
                            "TRUE",
                            "1",
                        )
                    else:
                        # Boolean or numeric values
                        column.computed_stored = bool(is_stored_value)
            elif getattr(column, "is_computed", False):
                # Column was marked as computed but we couldn't find expression.
                # Clear the flag to avoid generating invalid SQL.
                # This handles cases where a catalog source marks columns as computed
                # even though the dialect query has no expression for them.
                si.log.debug(
                    f"Column {column.name} was marked as computed but no expression "
                    "found, clearing is_computed flag"
                )
                column.is_computed = False
                column.computed_expression = None

        if computed_map:
            si.log.debug(
                f"Enriched {len(computed_map)} computed columns with detailed "
                f"metadata for {schema}.{table}"
            )

    except Exception as e:
        si.log.warning(f"Error enriching computed columns for {schema}.{table}: {e}")
        si.log.debug(f"Traceback: {traceback.format_exc()}")
        si.log.warning(
            f"Could not enrich computed columns with detailed metadata "
            f"for {schema}.{table}: {e}"
        )


def enrich_columns_with_identity(
    si: "SchemaIntrospector", schema: str, table: str, columns: List["SqlColumn"]
) -> None:
    """Enrich *columns* with identity/auto-increment metadata.

    The base column extractor loads the coarse identity flag from the
    plugin's column query. This pass enriches matching columns with seed,
    increment, and current-value details from the plugin's identity query.
    """
    # Columns may already have is_identity set from the plugin's column query.
    # This method adds detailed metadata (seed, increment) from vendor queries

    # Try to add detailed metadata from vendor queries if available
    if not si.vendor_queries:
        return

    # Ensure we have a connection without requesting metadata on native providers.
    if getattr(si.provider, "provider_transport", "native") == "native":
        si._ensure_native_connection()
    else:
        si._ensure_metadata()

    try:
        sql, params = si.vendor_queries.get_identity_columns_query(schema, table)
        if not sql:
            return

        results = si.provider.query_executor.execute_query(si.connection, sql, params)

        # Create a mapping of column name to identity metadata
        identity_map = {}
        for row in results:
            column_name = (
                si._get_row_value(row, "column_name")
                or row.get("COLUMN_NAME")
                or row.get("column_name")
            )
            if column_name:
                identity_map[column_name.upper()] = {
                    "seed_value": (
                        si._get_row_value(row, "seed_value")
                        or row.get("SEED_VALUE")
                        or row.get("seed_value")
                    ),
                    "increment_value": (
                        si._get_row_value(row, "increment_value")
                        or row.get("INCREMENT_VALUE")
                        or row.get("increment_value")
                    ),
                    "last_value": (
                        si._get_row_value(row, "last_value")
                        or row.get("LAST_VALUE")
                        or row.get("last_value")
                    ),
                }

        # Enrich matching columns with detailed metadata
        for column in columns:
            identity_data = identity_map.get(column.name.upper())
            if identity_data:
                # Mark as identity (may already be marked from the column query)
                column.is_identity = True
                # Add detailed metadata
                column.identity_seed = identity_data["seed_value"]
                column.identity_increment = identity_data["increment_value"]
                # Note: last_value is not part of SQL Model, store as custom attribute if needed
                if identity_data["last_value"] is not None:
                    column.identity_last_value = identity_data["last_value"]  # type: ignore[attr-defined]

        if identity_map:
            si.log.debug(
                f"Enriched {len(identity_map)} identity columns with detailed "
                f"metadata for {schema}.{table}"
            )

    except Exception as e:
        si.log.warning(
            f"Could not enrich identity columns with detailed metadata "
            f"for {schema}.{table}: {e}"
        )
