"""
ISP-01: Focused Protocol interfaces for VendorMetadataQueries.

``VendorMetadataQueries`` (825 lines, 31+ methods) mixes five distinct
responsibilities into one ABC.  These Protocols document and enforce the
interface segregation principle without touching existing implementations:
each concrete class (PostgreSQLMetadataQueries, OracleMetadataQueries, …)
already satisfies all five protocols structurally.

Usage (type-hint / documentation only)::

    def build_table_extractor(queries: ITableQueries) -> TableExtractor: ...
    def build_view_extractor(queries: IViewQueries) -> ViewExtractor: ...

Callers that only need one capability can declare a narrower type, making
their dependencies explicit and their tests easier to mock.

Note:
    These protocols are purely structural (``runtime_checkable``).
    ``VendorMetadataQueries`` is NOT modified; it inherits from ``ABC`` and
    continues to be the concrete base class for all vendor implementations.
    The protocols serve as lightweight documentation and optional type-hint
    targets for new code.
"""

from typing import Any, List, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# ITableQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class ITableQueries(Protocol):
    """Queries related to table structure and properties.

    Covers: partitions, inheritance, row-level security, policies, table
    properties, partition schemes, and partitioned-table listings.
    """

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for table partition information."""
        ...

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for table-level properties (engine, charset, etc.)."""
        ...

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for the partition scheme of a table."""
        ...

    def get_table_inheritance_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for table inheritance information (PostgreSQL)."""
        ...

    def get_table_row_security_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for row-level security status (PostgreSQL)."""
        ...

    def get_policies_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for row-level security policies (PostgreSQL)."""
        ...

    def get_partitioned_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for all partitioned tables in a schema."""
        ...

    def supports_partitions(self) -> bool:
        """Whether this dialect supports partition introspection."""
        ...


# ---------------------------------------------------------------------------
# IViewQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class IViewQueries(Protocol):
    """Queries related to views and materialized views."""

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for views in a schema."""
        ...

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for the definition of a specific view."""
        ...

    def get_materialized_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for materialized views in a schema."""
        ...

    def supports_views(self) -> bool:
        """Whether this dialect supports view introspection."""
        ...

    def supports_materialized_views(self) -> bool:
        """Whether this dialect supports materialized view introspection."""
        ...


# ---------------------------------------------------------------------------
# IConstraintQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class IConstraintQueries(Protocol):
    """Queries related to constraints (check, unique)."""

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for check constraints of a table."""
        ...

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for unique constraints of a table."""
        ...

    def supports_check_constraints(self) -> bool:
        """Whether this dialect supports check constraint introspection."""
        ...


# ---------------------------------------------------------------------------
# ISequenceQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class ISequenceQueries(Protocol):
    """Queries related to sequences."""

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for sequences in a schema."""
        ...

    def supports_sequences(self) -> bool:
        """Whether this dialect supports sequences."""
        ...


# ---------------------------------------------------------------------------
# IIndexQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class IIndexQueries(Protocol):
    """Queries related to indexes."""

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for detailed index information on a table."""
        ...

    def get_all_indexes_query(self, schema: str) -> Optional[tuple[str, List[Any]]]:
        """Return (sql, params) for all indexes in a schema, or None if unsupported."""
        ...


# ---------------------------------------------------------------------------
# IStoredObjectQueries
# ---------------------------------------------------------------------------


@runtime_checkable
class IStoredObjectQueries(Protocol):
    """Queries related to stored objects: procedures, functions, triggers,
    synonyms, packages, events, and user-defined types.
    """

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for stored procedures in a schema."""
        ...

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for functions in a schema."""
        ...

    def get_procedure_parameters_query(
        self, schema: str, procedure_name: str
    ) -> tuple[str, List[Any]]:
        """Return (sql, params) for parameters of a specific procedure/function."""
        ...

    def get_triggers_query(self, schema: str, table: Optional[str] = None) -> tuple[str, List[Any]]:
        """Return (sql, params) for triggers."""
        ...

    def get_synonyms_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for synonyms in a schema."""
        ...

    def get_packages_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for packages in a schema (Oracle/DB2)."""
        ...

    def get_events_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for scheduled events (MySQL)."""
        ...

    def get_user_defined_types_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return (sql, params) for user-defined types in a schema."""
        ...

    def supports_procedures(self) -> bool:
        """Whether this dialect supports procedure introspection."""
        ...

    def supports_functions(self) -> bool:
        """Whether this dialect supports function introspection."""
        ...

    def supports_triggers(self) -> bool:
        """Whether this dialect supports trigger introspection."""
        ...

    def supports_synonyms(self) -> bool:
        """Whether this dialect supports synonym introspection."""
        ...

    def supports_user_defined_types(self) -> bool:
        """Whether this dialect supports user-defined type introspection."""
        ...
