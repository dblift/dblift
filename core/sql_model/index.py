"""Dialect-agnostic ``Index`` SQL object — covers unique/non-unique and functional indexes."""

from typing import Any, Dict, List, Optional, Sequence

from core.sql_model.base import SqlObject, SqlObjectType


def _quirks_for(dialect: Optional[str]) -> Any:
    """Resolve quirks for *dialect* via the registry.

    Story 26-5: replaces the inline ``if dialect in {...}`` dispatch
    in the index DDL paths. Returns ``BaseQuirks`` defaults when the
    dialect is unknown.
    """
    from db.base_quirks import BaseQuirks
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(dialect or "")
    if canonical:
        return ProviderRegistry.get_quirks(canonical)
    return BaseQuirks()


class Index(SqlObject):
    """Represents a database index."""

    def __init__(
        self,
        name: str,
        table_name: str,
        columns: List[str],
        schema: Optional[str] = None,
        table_schema: Optional[str] = None,
        unique: bool = False,
        type: str = "BTREE",
        condition: Optional[str] = None,
        include_columns: Optional[List[str]] = None,
        sort_directions: Optional[List[str]] = None,
        dialect: Optional[str] = None,
        # Grammar-based: MySQL-specific index properties
        online: Optional[bool] = None,  # True for ONLINE, False for OFFLINE (MySQL)
        # Grammar-based: PostgreSQL-specific index properties
        concurrently: bool = False,  # CONCURRENTLY keyword (PostgreSQL)
        # Grammar-based: Oracle-specific index properties
        tablespace: Optional[str] = None,  # TABLESPACE clause (Oracle)
        is_local: Optional[bool] = None,  # LOCAL bitmap indexes on partitioned tables (Oracle)
        expression_flags: Optional[List[bool]] = None,
        # Index storage properties - SQL-generation-only
        fillfactor: Optional[
            int
        ] = None,  # Fillfactor (PostgreSQL, SQL Server) - SQL-generation-only
        compression: Optional[str] = None,  # Compression settings - SQL-generation-only
        comment: Optional[str] = None,  # Index comment - SQL-generation-only
        definition: Optional[str] = None,  # Preserved vendor DDL, e.g. Oracle domain indexes
    ):
        """Initialize an index.

        Args:
            name: Index name
            table_name: Name of the table being indexed
            columns: List of indexed columns
            schema: Schema name for the index
            table_schema: Schema name for the table (if different from index schema)
            unique: Whether this is a unique index
            type: Index type (BTREE, HASH, FULLTEXT, SPATIAL, etc.)
            condition: Optional WHERE condition
            include_columns: Optional INCLUDE columns (SQL Server)
            sort_directions: Optional sort directions (ASC/DESC) for each column
            dialect: SQL dialect
            online: Whether index was created with ONLINE (True) or OFFLINE (False) (MySQL grammar-based)
            concurrently: Whether index was created CONCURRENTLY (PostgreSQL grammar-based)
            tablespace: Tablespace name for the index (Oracle grammar-based)
            fillfactor: Fillfactor percentage (PostgreSQL, SQL Server) - SQL-generation-only
            compression: Compression settings - SQL-generation-only
            comment: Index comment/description - SQL-generation-only
        """
        super().__init__(name, SqlObjectType.INDEX, schema, dialect)
        self.table_name = table_name
        self.columns = columns
        # If table_schema is not provided, use the index schema
        self.table_schema = table_schema if table_schema is not None else schema
        self.unique = unique
        self.type = type
        self.condition = condition
        self.include_columns = self._normalize_include_columns(include_columns)
        self.sort_directions = sort_directions or []
        # Grammar-based index properties.
        self.online = online  # MySQL ``ONLINE`` / ``OFFLINE``
        self.concurrently = concurrently  # PostgreSQL ``CREATE INDEX CONCURRENTLY``
        self.tablespace = tablespace  # Oracle ``TABLESPACE`` clause
        self.is_local = is_local  # Oracle ``LOCAL`` partitioned-index keyword
        expr_flags = expression_flags or []
        self.expression_flags = [
            bool(expr_flags[i]) if i < len(expr_flags) else False for i in range(len(columns))
        ]
        # Index storage properties - SQL-generation-only
        self.fillfactor = fillfactor
        self.compression = compression
        self.comment = comment
        self.definition = definition

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

    def _render_with_options(self, style: str) -> str:
        """Render the ``WITH (...)`` storage-options clause.

        Style is ``"lowercase"`` (PG: ``fillfactor=...``),
        ``"uppercase"`` (SQL Server: ``FILLFACTOR=...``), or ``""``
        (no options supported — empty string).
        """
        if not style or (self.fillfactor is None and not self.compression):
            return ""
        if style == "uppercase":
            opts = []
            if self.fillfactor is not None:
                opts.append(f"FILLFACTOR = {self.fillfactor}")
            if self.compression:
                opts.append(f"DATA_COMPRESSION = {self.format_identifier(self.compression)}")
            return f" WITH ({', '.join(opts)})"
        # ``lowercase`` (PG)
        opts = []
        if self.fillfactor is not None:
            opts.append(f"fillfactor = {self.fillfactor}")
        if self.compression:
            opts.append(f"compression = {self.format_identifier(self.compression)}")
        return f" WITH ({', '.join(opts)})"

    @property
    def drop_statement(self) -> str:
        """Generate DROP INDEX statement.

        Returns:
            SQL DROP INDEX statement for this index
        """
        schema_prefix = self.format_identifier(self.schema) + "." if self.schema else ""
        idx_name = self.format_identifier(self.name)
        table_name = self.format_identifier(self.table_name)
        table_schema_prefix = (
            self.format_identifier(self.table_schema) + "." if self.table_schema else ""
        )

        # Story 26-5: DROP INDEX shape comes from plugin Quirks.
        quirks = _quirks_for(self.dialect)
        if quirks.index_drop_includes_table:
            if_exists = "IF EXISTS " if quirks.index_drop_table_form_supports_if_exists else ""
            return f"DROP INDEX {if_exists}{idx_name} ON {table_schema_prefix}{table_name}"
        # Standalone form (PostgreSQL, SQLite: IF EXISTS; Oracle, DB2: no IF EXISTS).
        if_exists = "IF EXISTS " if quirks.index_drop_standalone_supports_if_exists else ""
        return f"DROP INDEX {if_exists}{schema_prefix}{idx_name}"

    @staticmethod
    def _normalize_include_columns(include_columns: Optional[Sequence[Any]]) -> List[str]:
        """Normalize INCLUDE column payloads to plain strings."""
        normalized: List[str] = []
        if not include_columns:
            return normalized
        for entry in include_columns:
            if entry is None:
                continue
            if isinstance(entry, dict):
                name = entry.get("name")
                if name is None and entry:
                    name = next(iter(entry.values()))
                if name is None:
                    continue
                normalized.append(str(name))
            else:
                normalized.append(str(entry))
        return normalized

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Index":
        """Create index from dictionary representation.

        Args:
            data: Dictionary with index attributes

        Returns:
            Index object
        """
        return cls(
            name=data["name"],
            table_name=data["table_name"],
            columns=data["columns"],
            schema=data.get("schema"),
            table_schema=data.get("table_schema"),
            unique=data.get("unique", False),
            type=data.get("type", "BTREE"),
            condition=data.get("condition"),
            include_columns=data.get("include_columns"),
            sort_directions=data.get("sort_directions"),
            dialect=data.get("dialect"),
            online=data.get("online"),
            concurrently=data.get("concurrently", False),
            tablespace=data.get("tablespace"),
            is_local=data.get("is_local"),
            expression_flags=data.get("expression_flags"),
            fillfactor=data.get("fillfactor"),
            compression=data.get("compression"),
            comment=data.get("comment"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert index to dictionary representation.

        Returns:
            Dictionary with index attributes
        """
        return {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "table_name": self.table_name,
            "table_schema": self.table_schema,
            "columns": self.columns,
            "unique": self.unique,
            "type": self.type,
            "condition": self.condition,
            "include_columns": self.include_columns,
            "sort_directions": self.sort_directions,
            "online": self.online,
            "concurrently": self.concurrently,
            "tablespace": self.tablespace,
            "is_local": self.is_local,
            "expression_flags": self.expression_flags,
            "fillfactor": self.fillfactor,
            "compression": self.compression,
            "comment": self.comment,
        }
