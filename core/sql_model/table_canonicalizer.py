"""Conservative canonicalizer for Table objects at the snapshot/live boundary.

Normalizes constraint default-flag values so snapshot-loaded and live-introspected
Tables produce identical DDL when semantically equivalent. Mirrors the equality
semantics in core.sql_model.base._norm_constraint_deferrable / _norm_constraint_enabled:

- is_deferrable, initially_deferred: SQL default is NOT DEFERRABLE; collapse False -> None
- is_enabled, is_validated:          SQL default is ENABLED/VALIDATED; collapse True -> None

Intentionally non-destructive: no constraint dedup, no type rewriting, no name cleanup.
Aggressive operations live in provider-specific SQL generation and stay opt-in.
"""

from typing import Iterable, List

from core.sql_model.table import Table


class TableCanonicalizer:
    """Collapses constraint default flags to None so snapshot and live forms match."""

    def canonicalize(self, table: Table) -> Table:
        """Normalize ``table`` in place so default constraint flags collapse to ``None``."""
        if not table.constraints:
            return table

        for constraint in table.constraints:
            if constraint.is_deferrable is False:
                constraint.is_deferrable = None
            if constraint.initially_deferred is False:
                constraint.initially_deferred = None
            if constraint.is_enabled is True:
                constraint.is_enabled = None
            if constraint.is_validated is True:
                constraint.is_validated = None

        return table

    def canonicalize_tables(self, tables: Iterable[Table]) -> List[Table]:
        """Canonicalize every table in ``tables`` and return them as a list."""
        result = []
        for table in tables:
            self.canonicalize(table)
            result.append(table)
        return result
