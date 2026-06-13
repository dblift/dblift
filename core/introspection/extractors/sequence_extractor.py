"""
Sequence extractor for schema introspection.

This module extracts sequence metadata from databases using vendor-specific queries.
"""

import logging
from typing import List

from core.introspection._utils import get_row_value, to_int
from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.sequence import Sequence

logger = logging.getLogger(__name__)


class SequenceExtractor(BaseExtractor):
    """
    Extractor for sequences.

    This extractor handles sequence metadata extraction using vendor-specific queries
    for comprehensive metadata coverage.
    """

    def get_sequences(self, schema: str) -> List[Sequence]:
        """
        Get sequences in a schema using vendor-specific queries.

        Args:
            schema: Schema name

        Returns:
            List of Sequence objects
        """
        if not self.vendor_queries or not self.vendor_queries.supports_sequences():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_sequences_query(schema)
            query_executor = getattr(self.provider, "query_executor", None)
            if query_executor is not None:
                results = query_executor.execute_query(self.connection, sql, params)
            else:
                results = self.provider.execute_query(sql, params)

            sequences = []
            for row in results:
                sequence_name = get_row_value(row, "sequence_name")
                if not sequence_name:
                    continue

                # Track sequence capture status
                sequence_status = None
                if self.result_tracker:
                    sequence_status = self.result_tracker._track_object_status(
                        "sequence", sequence_name, schema
                    )

                # Handle cycle_option: YES/NO (PostgreSQL) or Y/N (Oracle cycle_flag)
                cycle_val = (
                    get_row_value(row, "cycle_option") or get_row_value(row, "cycle_flag") or "NO"
                ).upper()
                is_cycle = cycle_val in ("YES", "Y")

                # Dialect-specific ``temporary`` flag — routed through
                # the per-plugin quirks hook (PG sequences only).
                from db.provider_registry import ProviderRegistry

                quirks = ProviderRegistry.get_quirks(self.dialect or "")
                is_temp = quirks.is_temporary_sequence(row)

                sequence = Sequence(
                    name=sequence_name,
                    schema=schema,
                    start_with=to_int(
                        get_row_value(row, "start_value") or get_row_value(row, "last_number")
                    ),
                    increment_by=to_int(
                        get_row_value(row, "increment") or get_row_value(row, "increment_by")
                    ),
                    min_value=to_int(
                        get_row_value(row, "minimum_value") or get_row_value(row, "min_value")
                    ),
                    max_value=to_int(
                        get_row_value(row, "maximum_value") or get_row_value(row, "max_value")
                    ),
                    cycle=is_cycle,
                    cache=to_int(get_row_value(row, "cache_size")),
                    dialect=self.dialect,
                    temp=is_temp,
                )
                owning_schema = get_row_value(row, "owning_schema")
                owning_table = get_row_value(row, "owning_table")
                owning_column = get_row_value(row, "owning_column")
                if owning_table:
                    sequence.owned_by_table = (
                        f"{owning_schema}.{owning_table}" if owning_schema else owning_table
                    )
                if owning_column:
                    sequence.owned_by_column = owning_column
                # Dialect-specific "is this sequence internal / synthetic"
                # filter — Oracle hides ``ISEQ$$_<oid>`` auto-IDENTITY
                # backing sequences here.
                if quirks.is_internal_sequence(sequence):
                    continue

                # Track property capture
                if sequence_status:
                    sequence_status.add_property_status(
                        "start_with", sequence.start_with is not None
                    )
                    sequence_status.add_property_status(
                        "increment_by", sequence.increment_by is not None
                    )
                    sequence_status.add_property_status("min_value", sequence.min_value is not None)
                    sequence_status.add_property_status("max_value", sequence.max_value is not None)

                sequences.append(sequence)

            if len(sequences) > 0:
                self.log.debug(f"Found {len(sequences)} sequences in schema {schema}")

            return sequences

        except Exception as e:
            logger.warning(f"Error getting sequences for schema {schema}: {e}")
            self.log.warning(f"Could not get sequences for schema {schema}: {e}")
            if self.result_tracker:
                self.result_tracker._track_error(
                    f"Error getting sequences: {e}",
                    object_type="schema",
                    object_name=schema,
                    property_name="sequences",
                    exception=e,
                )
            return []
