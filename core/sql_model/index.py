"""Dialect-agnostic ``Index`` SQL object — covers unique/non-unique and functional indexes."""

from typing import Any, Dict, List, Optional, Sequence

from core.sql_model.base import SqlObject, SqlObjectType

_NS_MYSQL = "mysql"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_ORACLE = "oracle"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_POSTGRES = "postgresql"  # lint: allow-dialect-string: plugin namespace key for dialect_options


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
        # ``dialect_options`` is initialized by ``SqlObject.__init__``; the
        # property setters below route into it under their plugin namespace.
        self.online = online
        self.concurrently = concurrently
        self.tablespace = tablespace
        self.is_local = is_local
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
    def online(self) -> Optional[bool]:
        """MySQL ``ONLINE`` / ``OFFLINE`` index keyword."""
        return self.get_dialect_option(_NS_MYSQL, "online")

    @online.setter
    def online(self, value: Optional[bool]) -> None:
        """Set MySQL ``ONLINE`` / ``OFFLINE`` index keyword."""
        self._set_plugin_option(_NS_MYSQL, "online", value)

    @property
    def concurrently(self) -> bool:
        """PostgreSQL ``CREATE INDEX CONCURRENTLY`` flag."""
        return bool(self.get_dialect_option(_NS_POSTGRES, "concurrently", default=False))

    @concurrently.setter
    def concurrently(self, value: bool) -> None:
        """Set PostgreSQL ``CREATE INDEX CONCURRENTLY`` flag."""
        self._set_plugin_option(_NS_POSTGRES, "concurrently", value, default=False)

    @property
    def tablespace(self) -> Optional[str]:
        """Oracle ``TABLESPACE`` clause."""
        value = self.get_dialect_option(_NS_ORACLE, "tablespace")
        return value if value is None or isinstance(value, str) else str(value)

    @tablespace.setter
    def tablespace(self, value: Optional[str]) -> None:
        """Set Oracle ``TABLESPACE`` clause."""
        self._set_plugin_option(_NS_ORACLE, "tablespace", value)

    @property
    def is_local(self) -> Optional[bool]:
        """Oracle ``LOCAL`` partitioned-index keyword."""
        return self.get_dialect_option(_NS_ORACLE, "is_local")

    @is_local.setter
    def is_local(self, value: Optional[bool]) -> None:
        """Set Oracle ``LOCAL`` partitioned-index keyword."""
        self._set_plugin_option(_NS_ORACLE, "is_local", value)

    @property
    def create_statement(self) -> str:
        """Generate CREATE INDEX statement using database-specific generators.

        Returns:
            Dialect-specific CREATE INDEX statement
        """
        # Use the appropriate SQL generator for the dialect
        from core.sql_generator.generator_factory import (
            SqlGeneratorFactory,
        )

        try:
            generator = SqlGeneratorFactory.create(
                self.dialect or "postgresql"  # lint: allow-dialect-string: factory default fallback
            )
            # Check if generator has the new method
            if hasattr(generator, "generate_create_statement"):
                result = generator.generate_create_statement(self)
                return str(result)
            else:
                # Fallback for old generators that don't have the method yet
                return self._generate_basic_create_statement()
        except (ValueError, ImportError, AttributeError):
            # Fallback to basic CREATE INDEX if generator not available
            return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE INDEX statement as fallback.

        Story 26-5: dialect dispatch goes through plugin Quirks.
        """
        quirks = _quirks_for(self.dialect)

        schema_name = self.format_identifier(self.schema) if self.schema else ""
        idx_name = self.format_identifier(self.name)
        table_schema_name = self.format_identifier(self.table_schema) if self.table_schema else ""
        table_name = self.format_identifier(self.table_name)

        schema_prefix = (
            f"{schema_name}." if schema_name and quirks.index_qualifies_with_schema else ""
        )
        table_schema_prefix = f"{table_schema_name}." if table_schema_name else ""

        index_type_upper = self.type.upper() if self.type else "BTREE"

        stmt = "CREATE "
        if quirks.index_supports_online_offline:
            if self.online is True:
                stmt += "ONLINE "
            elif self.online is False:
                stmt += "OFFLINE "
        if self.unique:
            stmt += "UNIQUE "
        if self.concurrently and quirks.supports_concurrent_index:
            stmt += "CONCURRENTLY "
        if quirks.index_supports_mysql_typed_keywords:
            if index_type_upper in ("FULLTEXT", "SPATIAL"):
                stmt += f"{index_type_upper} "
            elif index_type_upper != "BTREE":
                stmt += f"{self.type} "

        stmt += f"INDEX {schema_prefix}{idx_name} ON {table_schema_prefix}{table_name}"

        if quirks.index_supports_using_clause and index_type_upper != "BTREE":
            stmt += f" USING {index_type_upper}"

        # Some index types skip ASC/DESC sort directions.
        supports_sort = index_type_upper not in quirks.index_no_sort_types

        use_sort = (
            supports_sort
            and self.sort_directions
            and len(self.sort_directions) == len(self.columns)
        )
        column_list = []
        for idx, col in enumerate(self.columns):
            is_expression = (
                self.expression_flags[idx] if idx < len(self.expression_flags) else False
            )
            formatted_column = col if is_expression else self.format_identifier(col)
            if use_sort:
                direction = self.sort_directions[idx]
                column_list.append(f"{formatted_column} {direction}")
            else:
                column_list.append(formatted_column)

        stmt += f" ({', '.join(column_list)})"

        if quirks.index_supports_local_partitioned and self.is_local:
            stmt += " LOCAL"

        # INCLUDE / WHERE clauses are generic.
        if self.include_columns:
            include_columns = [self.format_identifier(col) for col in self.include_columns]
            stmt += f" INCLUDE ({', '.join(include_columns)})"

        if self.condition:
            stmt += f" WHERE {self.condition}"

        if quirks.index_supports_bitmap and self.type == "BITMAP":
            stmt = stmt.replace("INDEX", "BITMAP INDEX")

        if quirks.index_supports_tablespace and self.tablespace:
            stmt += f" TABLESPACE {self.format_identifier(self.tablespace)}"

        # WITH (...) storage options — case-style depends on dialect.
        with_clause = self._render_with_options(quirks.index_with_options_style)
        if with_clause:
            stmt += with_clause

        return stmt

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
