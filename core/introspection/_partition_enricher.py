"""Partition-scheme enrichment helpers for ``SchemaIntrospector``.

Extracted from :mod:`core.introspection.schema_introspector` to keep the
orchestrator focused. ``SchemaIntrospector`` keeps thin wrapper methods
(``enrich_table_with_partition_scheme``, ``get_table_partitions``) that
delegate here, preserving the public surface used by tests and callers.

The two helpers take the introspector instance as their first parameter
(``si``) instead of being bound methods so the dependency on
``self.vendor_queries`` / ``self.provider`` / ``self.connection`` /
``self.dialect`` / ``self.log`` and the helper accessors
``self._get_row_value`` / ``self._normalize_oracle_partition_bound`` /
``self._ensure_metadata`` is explicit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from core.introspection.schema_introspector import SchemaIntrospector
    from core.sql_model.table import Table


def enrich_table_with_partition_scheme(
    si: "SchemaIntrospector", schema: str, table_name: str, table: "Table"
) -> None:
    """Enrich *table* with partition scheme (method and columns).

    Does NOT track individual partitions to avoid drift from auto-created
    partitions (e.g., Oracle INTERVAL partitions).
    """
    try:
        # Check if vendor queries support partition scheme query
        sql, params = si.vendor_queries.get_partition_scheme_query(schema, table_name)  # type: ignore[union-attr]
        if not sql:
            return

        results = si.provider.query_executor.execute_query(si.connection, sql, params)
        if not results:
            return  # Table not partitioned

        row = results[0]

        # Plugin-specific row parsing — each dialect projects partition
        # method + columns differently (Oracle partitioning_type, PG
        # ``partition_definition``, MySQL method+expression, DB2
        # ``partition_definition``, SQL Server function+type+columns).
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(si.dialect or "")
        quirks.extract_partition_scheme_from_row(si, row, table)

        if table.partition_method:
            si.log.info(
                f"Enriched table {schema}.{table_name} with partition scheme: "
                f"method={table.partition_method}, columns={table.partition_columns}"
            )

    except Exception as e:
        si.log.warning(f"Error enriching partition scheme for {schema}.{table_name}: {e}")


def _normalize_partition_bound(si: Any, value: Any) -> Any:
    """Route partition-bound normalization through the plugin's quirks
    (Oracle collapses TO_DATE-wrapped midnight literals; other dialects
    no-op)."""
    from db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(si.dialect or "")
    return quirks.normalize_partition_bound(value)


def get_table_partitions(si: "SchemaIntrospector", schema: str, table: str) -> List[Any]:
    """Return the list of ``Partition`` objects for *table*."""
    from core.sql_model.partition import Partition

    if not si.vendor_queries or not si.vendor_queries.supports_partitions():
        return []

    # Ensure we have a connection without requesting metadata on native providers.
    if getattr(si.provider, "provider_transport", "native") == "native":
        si._ensure_native_connection()
    else:
        si._ensure_metadata()

    try:
        sql, params = si.vendor_queries.get_table_partitions_query(schema, table)
        if not sql:
            return []

        results = si.provider.query_executor.execute_query(si.connection, sql, params)

        partitions = []
        for row in results:
            partition_name = (
                si._get_row_value(row, "partition_name")
                or row.get("PARTITION_NAME")
                or row.get("partition_name")
            )
            partition_method = (
                si._get_row_value(row, "partition_method")
                or row.get("PARTITION_METHOD")
                or row.get("partition_method")
            )
            partition_expression = (
                si._get_row_value(row, "partition_expression")
                or row.get("PARTITION_EXPRESSION")
                or row.get("partition_expression")
            )
            high_value = (
                si._get_row_value(row, "high_value")
                or row.get("HIGH_VALUE")
                or row.get("high_value")
            )
            high_value = _normalize_partition_bound(si, high_value)
            low_value = (
                si._get_row_value(row, "low_value") or row.get("LOW_VALUE") or row.get("low_value")
            )
            low_value = _normalize_partition_bound(si, low_value)
            partition_number = (
                si._get_row_value(row, "partition_number")
                or row.get("PARTITION_NUMBER")
                or row.get("partition_number")
            )

            # Filter out empty/null partitions (some DBs return rows for non-partitioned tables).
            # A valid partition should have at least meaningful partition data
            # (bounds, values, etc.). Just having a partition name (like "PART0") without
            # bounds/values is not sufficient.
            is_valid_partition = False
            if high_value or low_value:
                # Has partition bounds/values - this is the most reliable indicator
                is_valid_partition = True
            elif partition_name and partition_number is not None and partition_number > 0:
                # Has both name and valid partition number (greater than 0)
                # This indicates a real partition, not just a default/placeholder
                is_valid_partition = True
            elif partition_number is not None and partition_number > 0 and partition_expression:
                # Has partition number and expression (for expression-based partitioning)
                is_valid_partition = True

            if not is_valid_partition:
                # Skip empty/null partitions (likely from non-partitioned tables).
                # This filters out cases where DB2 returns a row with only
                # partition_method="RANGE" and a placeholder name like "PART0" but no
                # actual partition data.
                si.log.debug(
                    f"Skipping invalid/empty partition for {schema}.{table}: "
                    f"name={partition_name}, number={partition_number}, "
                    f"high={high_value}, low={low_value}"
                )
                continue

            # Create partition description from high/low values
            partition_description = None
            if high_value:
                partition_description = f"VALUES LESS THAN ({high_value})"
            elif low_value:
                partition_description = f"VALUES IN ({low_value})"

            # Create Partition object
            partition = Partition(
                name=partition_name,
                table=table,
                partition_method=partition_method or "UNKNOWN",
                partition_expression=partition_expression,
                partition_description=partition_description,
                schema=schema,
                dialect=si.dialect,
                # Store additional metadata
                partition_number=partition_number,
                high_value=high_value,
                low_value=low_value,
            )
            partitions.append(partition)

        si.log.debug(f"Found {len(partitions)} partitions for {schema}.{table}")

        return partitions

    except Exception as e:
        si.log.warning(f"Could not get partitions for {schema}.{table}: {e}")
        return []
