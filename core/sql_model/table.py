"""Dialect-agnostic ``Table`` SQL object — columns, constraints, partitions, options."""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.sql_model.base import (
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
)
from core.sql_model.partition import Partition

_NS_MYSQL = "mysql"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_ORACLE = "oracle"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_POSTGRES = "postgresql"  # lint: allow-dialect-string: plugin namespace key for dialect_options
_NS_SQLSERVER = "sqlserver"  # lint: allow-dialect-string: plugin namespace key for dialect_options

if TYPE_CHECKING:
    from core.sql_model.table_options import TableOptions


class Table(SqlObject):
    """Represents a database table.

    SIMP-48: ``__init__`` only accepts base/structural parameters.

    Tier-3 plugin isolation (current):
    Dialect-specific options are stored in :attr:`dialect_options` keyed by
    plugin name, e.g. ``{"mysql": {"storage_engine": "InnoDB"}}``. Historical
    flat attributes (``storage_engine``, ``filegroup``, ``row_security``,
    ``pctfree``, ...) remain as property aliases that read/write the same
    dict, so legacy ``table.storage_engine = ...`` call sites keep working.

    The legacy :class:`core.sql_model.table_options.TableOptions` typed
    surface (``Table.from_options`` / ``Table.to_options``) still works and
    feeds through the same property aliases. New code should prefer
    :meth:`set_dialect_option` so the field is owned by the plugin namespace
    rather than the named-slot dataclass.
    """

    def __init__(
        self,
        name: str,
        columns: Optional[List[SqlColumn]] = None,
        schema: Optional[str] = None,
        constraints: Optional[List[SqlConstraint]] = None,
        temporary: bool = False,
        tablespace: Optional[str] = None,
        dialect: Optional[str] = None,
        comment: Optional[str] = None,
        partitions: Optional[List["Partition"]] = None,
        export_partitions: Optional[List["Partition"]] = None,
        object_type: SqlObjectType = SqlObjectType.TABLE,
    ):
        """Initialize a table with base/structural parameters only.

        Args:
            name: Table name
            columns: List of columns
            schema: Schema name (optional)
            constraints: List of constraints
            temporary: Whether the table is temporary
            tablespace: Tablespace name (optional)
            dialect: SQL dialect
            comment: Table comment/description (optional)
            partitions: List of Partition objects (optional)
            export_partitions: Partition definitions used for export-only DDL generation
            object_type: ``SqlObjectType.TABLE`` (default) or a derived variant

        For dialect-specific options (storage engine, system versioning,
        row-level security, Oracle storage parameters, etc.) build a
        ``TableOptions`` and call ``Table.from_options(...)`` instead.
        """
        super().__init__(name, object_type, schema, dialect)
        self.columns = columns or []

        # Ensure columns inherit the dialect
        for col in self.columns:
            if not hasattr(col, "dialect") or not col.dialect:
                col.dialect = dialect

        self.constraints = constraints or []

        # Ensure constraints inherit the dialect
        for constraint in self.constraints:
            if not hasattr(constraint, "dialect") or not constraint.dialect:
                constraint.dialect = dialect

        self.temporary = temporary
        self.tablespace = tablespace
        self.comment = comment
        self.partitions = partitions or []
        self.export_partitions = export_partitions or []

        # Dialect-specific attributes — defaults; populate via from_options() or direct assignment.
        # All MySQL / SQL Server / PostgreSQL / Oracle-DB2 table-options now live in
        # ``dialect_options`` under their plugin namespace (Tier-3 plugin isolation).
        # Property aliases below preserve historical ``table.<attr>`` call sites.
        # Derived table tracking (CTAS, LIKE, etc.)
        # Format: "CTAS" for AS SELECT, "LIKE:schema.table" for LIKE
        self.derived_from: Optional[str] = None
        self.raw_ddl: Optional[str] = None

        # Partition scheme tracking (strategy only, not individual partitions)
        # partition_method: RANGE, LIST, HASH, KEY (MySQL), INTERVAL (Oracle auto-partitioning)
        # partition_columns: Column(s) used for partitioning
        # Note: Individual partitions are NOT tracked to avoid drift from auto-created partitions
        self.partition_method: Optional[str] = None
        self.partition_columns: Optional[List[str]] = None

        # Dialect-specific key/value metadata (e.g. CosmosDB partition_key)
        self.metadata: Dict[str, str] = {}

        # Tier-3 plugin-separation scaffold. Plugins introducing NEW
        # ``dialect_options`` is initialized by ``SqlObject.__init__``; plugin
        # write sites use ``set_dialect_option`` / ``get_dialect_option`` from
        # the base class.

        self._column_map = {col.name.lower(): col for col in self.columns}

        # Track if tablespace was explicitly set
        if tablespace is not None:
            self.mark_property_explicit("tablespace")

    # ------------------------------------------------------------------
    # Tier-3b: legacy flat-attribute aliases backed by ``dialect_options``.
    # Each property keeps the historical ``table.<attr>`` call sites working
    # while the storage moves under the plugin namespace.
    # ------------------------------------------------------------------

    @property
    def storage_engine(self) -> Optional[str]:
        """MySQL storage engine (``InnoDB`` / ``MyISAM`` / …).

        Backed by ``dialect_options['mysql']['storage_engine']``.
        """
        value = self.get_dialect_option(_NS_MYSQL, "storage_engine")
        return value if value is None or isinstance(value, str) else str(value)

    @storage_engine.setter
    def storage_engine(self, value: Optional[str]) -> None:
        """Set MySQL storage engine (``InnoDB`` / ``MyISAM`` / …)."""
        self._set_plugin_option(_NS_MYSQL, "storage_engine", value)

    @property
    def row_format(self) -> Optional[str]:
        """MySQL ``ROW_FORMAT`` (``DYNAMIC`` / ``COMPACT`` / …)."""
        value = self.get_dialect_option(_NS_MYSQL, "row_format")
        return value if value is None or isinstance(value, str) else str(value)

    @row_format.setter
    def row_format(self, value: Optional[str]) -> None:
        """Set MySQL ``ROW_FORMAT`` (``DYNAMIC`` / ``COMPACT`` / …)."""
        self._set_plugin_option(_NS_MYSQL, "row_format", value)

    @property
    def table_collation(self) -> Optional[str]:
        """MySQL table-level ``COLLATE`` (``utf8mb4_unicode_ci`` / …)."""
        value = self.get_dialect_option(_NS_MYSQL, "table_collation")
        return value if value is None or isinstance(value, str) else str(value)

    @table_collation.setter
    def table_collation(self, value: Optional[str]) -> None:
        """Set MySQL table-level ``COLLATE`` (``utf8mb4_unicode_ci`` / …)."""
        self._set_plugin_option(_NS_MYSQL, "table_collation", value)

    @property
    def next_auto_increment(self) -> Optional[int]:
        """MySQL ``AUTO_INCREMENT = N`` seed value."""
        value = self.get_dialect_option(_NS_MYSQL, "next_auto_increment")
        if value is None:
            return None
        return value if isinstance(value, int) else int(value)

    @next_auto_increment.setter
    def next_auto_increment(self, value: Optional[int]) -> None:
        """Set MySQL ``AUTO_INCREMENT = N`` seed value."""
        self._set_plugin_option(_NS_MYSQL, "next_auto_increment", value)

    @property
    def create_options(self) -> Optional[str]:
        """MySQL ``CREATE_OPTIONS`` (free-form ``KEY_BLOCK_SIZE=4 …``)."""
        value = self.get_dialect_option(_NS_MYSQL, "create_options")
        return value if value is None or isinstance(value, str) else str(value)

    @create_options.setter
    def create_options(self, value: Optional[str]) -> None:
        """Set MySQL ``CREATE_OPTIONS`` (free-form ``KEY_BLOCK_SIZE=4 …``)."""
        self._set_plugin_option(_NS_MYSQL, "create_options", value)

    # ── SQL Server (T-SQL) ─────────────────────────────────────────

    @property
    def filegroup(self) -> Optional[str]:
        """SQL Server ``ON <filegroup>`` clause."""
        value = self.get_dialect_option(_NS_SQLSERVER, "filegroup")
        return value if value is None or isinstance(value, str) else str(value)

    @filegroup.setter
    def filegroup(self, value: Optional[str]) -> None:
        """Set SQL Server ``ON <filegroup>`` clause."""
        self._set_plugin_option(_NS_SQLSERVER, "filegroup", value)

    @property
    def memory_optimized(self) -> bool:
        """SQL Server HEKATON memory-optimized table flag."""
        return bool(self.get_dialect_option(_NS_SQLSERVER, "memory_optimized", default=False))

    @memory_optimized.setter
    def memory_optimized(self, value: bool) -> None:
        """Set SQL Server HEKATON memory-optimized table flag."""
        self._set_plugin_option(_NS_SQLSERVER, "memory_optimized", value, default=False)

    @property
    def system_versioned(self) -> bool:
        """SQL Server temporal-table ``SYSTEM_VERSIONING = ON`` flag."""
        return bool(self.get_dialect_option(_NS_SQLSERVER, "system_versioned", default=False))

    @system_versioned.setter
    def system_versioned(self, value: bool) -> None:
        """Set SQL Server temporal-table ``SYSTEM_VERSIONING = ON`` flag."""
        self._set_plugin_option(_NS_SQLSERVER, "system_versioned", value, default=False)

    @property
    def history_table(self) -> Optional[str]:
        """SQL Server temporal ``HISTORY_TABLE`` name."""
        value = self.get_dialect_option(_NS_SQLSERVER, "history_table")
        return value if value is None or isinstance(value, str) else str(value)

    @history_table.setter
    def history_table(self, value: Optional[str]) -> None:
        """Set SQL Server temporal ``HISTORY_TABLE`` name."""
        self._set_plugin_option(_NS_SQLSERVER, "history_table", value)

    @property
    def history_schema(self) -> Optional[str]:
        """SQL Server temporal ``HISTORY_TABLE`` schema."""
        value = self.get_dialect_option(_NS_SQLSERVER, "history_schema")
        return value if value is None or isinstance(value, str) else str(value)

    @history_schema.setter
    def history_schema(self, value: Optional[str]) -> None:
        """Set SQL Server temporal ``HISTORY_TABLE`` schema."""
        self._set_plugin_option(_NS_SQLSERVER, "history_schema", value)

    @property
    def period_start_column(self) -> Optional[str]:
        """SQL Server temporal ``PERIOD FOR SYSTEM_TIME`` start column."""
        value = self.get_dialect_option(_NS_SQLSERVER, "period_start_column")
        return value if value is None or isinstance(value, str) else str(value)

    @period_start_column.setter
    def period_start_column(self, value: Optional[str]) -> None:
        """Set SQL Server temporal ``PERIOD FOR SYSTEM_TIME`` start column."""
        self._set_plugin_option(_NS_SQLSERVER, "period_start_column", value)

    @property
    def period_end_column(self) -> Optional[str]:
        """SQL Server temporal ``PERIOD FOR SYSTEM_TIME`` end column."""
        value = self.get_dialect_option(_NS_SQLSERVER, "period_end_column")
        return value if value is None or isinstance(value, str) else str(value)

    @period_end_column.setter
    def period_end_column(self, value: Optional[str]) -> None:
        """Set SQL Server temporal ``PERIOD FOR SYSTEM_TIME`` end column."""
        self._set_plugin_option(_NS_SQLSERVER, "period_end_column", value)

    # ── PostgreSQL ──────────────────────────────────────────────────

    @property
    def row_security(self) -> bool:
        """PostgreSQL ``ALTER TABLE … ENABLE ROW LEVEL SECURITY``."""
        return bool(self.get_dialect_option(_NS_POSTGRES, "row_security", default=False))

    @row_security.setter
    def row_security(self, value: bool) -> None:
        """Set PostgreSQL ``ALTER TABLE … ENABLE ROW LEVEL SECURITY``."""
        self._set_plugin_option(_NS_POSTGRES, "row_security", value, default=False)

    @property
    def force_row_security(self) -> bool:
        """PostgreSQL ``FORCE ROW LEVEL SECURITY`` (applies RLS to table owners)."""
        return bool(self.get_dialect_option(_NS_POSTGRES, "force_row_security", default=False))

    @force_row_security.setter
    def force_row_security(self, value: bool) -> None:
        """Set PostgreSQL ``FORCE ROW LEVEL SECURITY`` (applies RLS to table owners)."""
        self._set_plugin_option(_NS_POSTGRES, "force_row_security", value, default=False)

    @property
    def policies(self) -> List[Dict[str, Any]]:
        """PostgreSQL row-level-security policies attached to the table."""
        value = self.get_dialect_option(_NS_POSTGRES, "policies", default=[])
        return value if isinstance(value, list) else []

    @policies.setter
    def policies(self, value: List[Dict[str, Any]]) -> None:
        """Set PostgreSQL row-level-security policies attached to the table."""
        self._set_plugin_option(_NS_POSTGRES, "policies", list(value or []), default=[])

    @property
    def inherits(self) -> List[str]:
        """PostgreSQL ``INHERITS (parent1, parent2)`` parent table list."""
        value = self.get_dialect_option(_NS_POSTGRES, "inherits", default=[])
        return value if isinstance(value, list) else []

    @inherits.setter
    def inherits(self, value: List[str]) -> None:
        """Set PostgreSQL ``INHERITS (parent1, parent2)`` parent table list."""
        self._set_plugin_option(_NS_POSTGRES, "inherits", list(value or []), default=[])

    # ── Oracle / DB2 storage ───────────────────────────────────────

    @property
    def pctfree(self) -> Optional[int]:
        """Oracle/DB2 ``PCTFREE`` storage parameter."""
        value = self.get_dialect_option(_NS_ORACLE, "pctfree")
        return value if value is None or isinstance(value, int) else int(value)

    @pctfree.setter
    def pctfree(self, value: Optional[int]) -> None:
        """Set Oracle/DB2 ``PCTFREE`` storage parameter."""
        self._set_plugin_option(_NS_ORACLE, "pctfree", value)

    @property
    def pctused(self) -> Optional[int]:
        """Oracle/DB2 ``PCTUSED`` storage parameter."""
        value = self.get_dialect_option(_NS_ORACLE, "pctused")
        return value if value is None or isinstance(value, int) else int(value)

    @pctused.setter
    def pctused(self, value: Optional[int]) -> None:
        """Set Oracle/DB2 ``PCTUSED`` storage parameter."""
        self._set_plugin_option(_NS_ORACLE, "pctused", value)

    @property
    def initial(self) -> Optional[int]:
        """Oracle/DB2 ``INITIAL`` extent size."""
        value = self.get_dialect_option(_NS_ORACLE, "initial")
        return value if value is None or isinstance(value, int) else int(value)

    @initial.setter
    def initial(self, value: Optional[int]) -> None:
        """Set Oracle/DB2 ``INITIAL`` extent size."""
        self._set_plugin_option(_NS_ORACLE, "initial", value)

    @property
    def next(self) -> Optional[int]:
        """Oracle/DB2 ``NEXT`` extent size."""
        value = self.get_dialect_option(_NS_ORACLE, "next")
        return value if value is None or isinstance(value, int) else int(value)

    @next.setter
    def next(self, value: Optional[int]) -> None:
        """Set Oracle/DB2 ``NEXT`` extent size."""
        self._set_plugin_option(_NS_ORACLE, "next", value)

    # ------------------------------------------------------------------
    # SIMP-48 — Typed-options surface (non-breaking).
    # ------------------------------------------------------------------

    @classmethod
    def from_options(
        cls,
        name: str,
        columns: Optional[List[SqlColumn]] = None,
        *,
        options: Optional["TableOptions"] = None,
        schema: Optional[str] = None,
        constraints: Optional[List[SqlConstraint]] = None,
        temporary: bool = False,
        tablespace: Optional[str] = None,
        dialect: Optional[str] = None,
        comment: Optional[str] = None,
        partitions: Optional[List["Partition"]] = None,
        export_partitions: Optional[List["Partition"]] = None,
        object_type: SqlObjectType = SqlObjectType.TABLE,
    ) -> "Table":
        """Build a ``Table`` and apply the typed dialect-specific options.

        The slim ``__init__`` only takes base parameters; dialect-specific
        attributes are populated from ``options`` post-construction. When
        ``options`` is ``None`` (the default), the dialect overlay is
        skipped and ``__init__`` defaults are preserved — important if
        ``__init__`` ever infers a dialect attribute from the ``dialect``
        parameter.
        """
        table = cls(
            name=name,
            columns=columns,
            schema=schema,
            constraints=constraints,
            temporary=temporary,
            tablespace=tablespace,
            dialect=dialect,
            comment=comment,
            partitions=partitions,
            export_partitions=export_partitions,
            object_type=object_type,
        )
        if options is not None:
            table._apply_options(options)
        return table

    def _apply_options(self, opts: "TableOptions") -> None:
        """Overlay typed dialect-specific options onto this table.

        Mutates self. Sibling of ``to_options`` — together they round-trip
        the dialect subset without going through the kwargs surface.
        """
        # MySQL
        self.storage_engine = opts.mysql.storage_engine
        self.row_format = opts.mysql.row_format
        self.table_collation = opts.mysql.table_collation
        self.next_auto_increment = opts.mysql.next_auto_increment
        self.create_options = opts.mysql.create_options
        # SQL Server
        self.filegroup = opts.sqlserver.filegroup
        self.memory_optimized = opts.sqlserver.memory_optimized
        self.system_versioned = opts.sqlserver.system_versioned
        self.history_table = opts.sqlserver.history_table
        self.history_schema = opts.sqlserver.history_schema
        self.period_start_column = opts.sqlserver.period_start_column
        self.period_end_column = opts.sqlserver.period_end_column
        # PostgreSQL
        self.row_security = opts.postgres.row_security
        self.force_row_security = opts.postgres.force_row_security
        self.policies = list(opts.postgres.policies)
        self.inherits = list(opts.postgres.inherits)
        # Oracle / DB2 storage
        self.pctfree = opts.oracle_storage.pctfree
        self.pctused = opts.oracle_storage.pctused
        self.initial = opts.oracle_storage.initial
        self.next = opts.oracle_storage.next
        # Misc
        self.derived_from = opts.derived_from
        self.raw_ddl = opts.raw_ddl

        # Track explicit T-SQL-specific properties for diff sensitivity
        if self.filegroup is not None:
            self.mark_property_explicit("filegroup")
        if self.memory_optimized:
            self.mark_property_explicit("memory_optimized")
        if self.system_versioned:
            self.mark_property_explicit("system_versioned")
        if self.history_table is not None:
            self.mark_property_explicit("history_table")
        if self.history_schema is not None:
            self.mark_property_explicit("history_schema")
        if self.period_start_column is not None:
            self.mark_property_explicit("period_start_column")
        if self.period_end_column is not None:
            self.mark_property_explicit("period_end_column")

    def to_options(self) -> "TableOptions":
        """Reconstruct the typed ``TableOptions`` view from this instance.

        Useful for codemods migrating legacy callers and for round-trip tests.
        """
        from core.sql_model.table_options import (
            MySqlTableOptions,
            OracleStorageOptions,
            PostgresTableOptions,
            SqlServerTableOptions,
            TableOptions,
        )

        return TableOptions(
            mysql=MySqlTableOptions(
                storage_engine=self.storage_engine,
                row_format=self.row_format,
                table_collation=self.table_collation,
                next_auto_increment=self.next_auto_increment,
                create_options=self.create_options,
            ),
            sqlserver=SqlServerTableOptions(
                filegroup=self.filegroup,
                memory_optimized=self.memory_optimized,
                system_versioned=self.system_versioned,
                history_table=self.history_table,
                history_schema=self.history_schema,
                period_start_column=self.period_start_column,
                period_end_column=self.period_end_column,
            ),
            postgres=PostgresTableOptions(
                row_security=self.row_security,
                force_row_security=self.force_row_security,
                policies=list(self.policies),
                inherits=list(self.inherits),
            ),
            oracle_storage=OracleStorageOptions(
                pctfree=self.pctfree,
                pctused=self.pctused,
                initial=self.initial,
                next=self.next,
            ),
            derived_from=self.derived_from,
            raw_ddl=self.raw_ddl,
        )

    def add_column(self, column: SqlColumn) -> None:
        """Add a column to the table.

        Args:
            column: The column to add
        """
        # Inherit dialect if needed
        if not hasattr(column, "dialect") or not column.dialect:
            column.dialect = self.dialect

        self.columns.append(column)
        self._column_map[column.name.lower()] = column

    def get_column(self, name: str) -> Optional[SqlColumn]:
        """Get a column by name.

        Args:
            name: Column name

        Returns:
            The column or None if not found
        """
        return self._column_map.get(name.lower())

    def add_constraint(self, constraint: SqlConstraint) -> None:
        """Add a constraint to the table.

        Args:
            constraint: The constraint to add
        """
        # Inherit dialect if needed
        if not hasattr(constraint, "dialect") or not constraint.dialect:
            constraint.dialect = self.dialect

        self.constraints.append(constraint)

    def get_primary_key(self) -> Optional[SqlConstraint]:
        """Get the primary key constraint.

        Returns:
            The primary key constraint or None if not found
        """
        for constraint in self.constraints:
            if constraint.constraint_type.value == "PRIMARY KEY":
                return constraint
        return None

    def get_foreign_keys(self) -> List[SqlConstraint]:
        """Get all foreign key constraints.

        Returns:
            List of foreign key constraints
        """
        return [c for c in self.constraints if c.constraint_type.value == "FOREIGN KEY"]

    def get_unique_constraints(self) -> List[SqlConstraint]:
        """Get all unique constraints.

        Returns:
            List of unique constraints
        """
        return [c for c in self.constraints if c.constraint_type.value == "UNIQUE"]

    def get_check_constraints(self) -> List[SqlConstraint]:
        """Get all check constraints.

        Returns:
            List of check constraints
        """
        return [c for c in self.constraints if c.constraint_type.value == "CHECK"]

    def generate_alter_table_check_constraints(self) -> List[str]:
        """Generate ALTER TABLE statements for CHECK constraints.

        Note: Only produces output for DB2 dialect. Returns empty list for all other dialects.
        """
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(self).generate_alter_check_constraints()

    def generate_alter_table_self_referencing_foreign_keys(self) -> List[str]:
        """Generate ALTER TABLE statements for self-referencing foreign keys.

        Note: Only produces output for DB2 dialect. Returns empty list for all other dialects.
        """
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(self).generate_alter_self_referencing_fks()

    @property
    def create_statement(self) -> str:
        """Generate CREATE TABLE statement using database-specific generators.

        Returns:
            Dialect-specific CREATE TABLE statement
        """
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        try:
            generator = SqlGeneratorFactory.create(
                self.dialect or "postgresql"  # lint: allow-dialect-string: factory default fallback
            )
            if not hasattr(generator, "generate_create_statement"):
                raise AttributeError("generator has no generate_create_statement")
            return str(generator.generate_create_statement(self))
        except (ValueError, ImportError, AttributeError):
            return BasicTableDdlGenerator(self).generate_create_statement()

    @property
    def drop_statement(self) -> str:
        """Generate DROP TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(self).generate_drop_statement()

    def __str__(self) -> str:
        """Return string representation of the table."""
        return self.create_statement

    def compare_with_defaults(
        self, other: "SqlObject", schema_defaults: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Compare two tables, taking into account schema defaults.

        This method extends the base class method to handle table-specific properties.

        Args:
            other: The other table to compare with
            schema_defaults: Dictionary of schema default values

        Returns:
            Dictionary of differences between the tables
        """
        # Get basic property differences from parent class
        differences = super().compare_with_defaults(other, schema_defaults)
        if "error" in differences:
            return differences

        schema_defaults = schema_defaults or {}

        # Only compare Table-specific properties if 'other' is a Table
        if not isinstance(other, Table):
            differences["error"] = "Cannot compare Table with non-Table object"
            return differences

        other_table = other

        # Compare tablespace only if explicitly set in one of the tables
        if self.is_property_explicit("tablespace") or (
            hasattr(other_table, "is_property_explicit")
            and other_table.is_property_explicit("tablespace")
        ):
            if self.tablespace != other_table.tablespace:
                differences["tablespace"] = {
                    "self": self.tablespace,
                    "other": other_table.tablespace,
                }

        # Compare temporary property
        if self.temporary != other_table.temporary:
            differences["temporary"] = {"self": self.temporary, "other": other_table.temporary}

        # T-SQL grammar-based: Compare filegroup (SQL Server).
        # Story 26-5: gate via plugin Quirks
        # (``table_uses_filegroup_syntax``).
        from db.provider_registry import ProviderRegistry

        def _filegroup_supported(dialect_name: Optional[str]) -> bool:
            if not dialect_name:
                return False
            canonical = ProviderRegistry.canonical_dialect_name(dialect_name)
            if not canonical:
                return False
            return ProviderRegistry.get_quirks(canonical).table_uses_filegroup_syntax

        if _filegroup_supported(self.dialect) or _filegroup_supported(other_table.dialect):
            if self.is_property_explicit("filegroup") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("filegroup")
            ):
                if self.filegroup != other_table.filegroup:
                    differences["filegroup"] = {
                        "self": self.filegroup,
                        "other": other_table.filegroup,
                    }

            # Compare memory-optimized property
            if self.is_property_explicit("memory_optimized") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("memory_optimized")
            ):
                if self.memory_optimized != other_table.memory_optimized:
                    differences["memory_optimized"] = {
                        "self": self.memory_optimized,
                        "other": other_table.memory_optimized,
                    }

            # Compare system-versioned property
            if self.is_property_explicit("system_versioned") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("system_versioned")
            ):
                if self.system_versioned != other_table.system_versioned:
                    differences["system_versioned"] = {
                        "self": self.system_versioned,
                        "other": other_table.system_versioned,
                    }
                # Also compare history table if system-versioned
                if self.system_versioned and other_table.system_versioned:
                    if self.history_table != other_table.history_table:
                        differences["history_table"] = {
                            "self": self.history_table,
                            "other": other_table.history_table,
                        }
                    if self.history_schema != other_table.history_schema:
                        differences["history_schema"] = {
                            "self": self.history_schema,
                            "other": other_table.history_schema,
                        }
                    if self.period_start_column != other_table.period_start_column:
                        differences["period_start_column"] = {
                            "self": self.period_start_column,
                            "other": other_table.period_start_column,
                        }
                    if self.period_end_column != other_table.period_end_column:
                        differences["period_end_column"] = {
                            "self": self.period_end_column,
                            "other": other_table.period_end_column,
                        }

        # Compare columns
        self_columns = {col.name.lower(): col for col in self.columns}
        other_columns = {col.name.lower(): col for col in other_table.columns}

        # Find columns only in self
        for name, col in self_columns.items():
            if name not in other_columns:
                if "columns_only_in_self" not in differences:
                    differences["columns_only_in_self"] = []
                differences["columns_only_in_self"].append(col.name)

        # Find columns only in other
        for name, col in other_columns.items():
            if name not in self_columns:
                if "columns_only_in_other" not in differences:
                    differences["columns_only_in_other"] = []
                differences["columns_only_in_other"].append(col.name)

        # Compare columns that exist in both
        column_differences: Dict[str, Dict[str, Any]] = {}
        for name, self_col in self_columns.items():
            if name in other_columns:
                other_col = other_columns[name]
                # Compare data types (required property)
                if self_col.data_type.lower() != other_col.data_type.lower():
                    if name not in column_differences:
                        column_differences[name] = {}
                    column_differences[name]["data_type"] = {
                        "self": self_col.data_type,
                        "other": other_col.data_type,
                    }

                # Compare nullable property if explicitly set in either column
                if (
                    hasattr(self_col, "is_property_explicit")
                    and self_col.is_property_explicit("nullable")
                    or hasattr(other_col, "is_property_explicit")
                    and other_col.is_property_explicit("nullable")
                ):
                    if self_col.nullable != other_col.nullable:
                        if name not in column_differences:
                            column_differences[name] = {}
                        column_differences[name]["nullable"] = {
                            "self": self_col.nullable,
                            "other": other_col.nullable,
                        }

                # Compare default value if explicitly set in either column
                if (
                    hasattr(self_col, "is_property_explicit")
                    and self_col.is_property_explicit("default_value")
                    or hasattr(other_col, "is_property_explicit")
                    and other_col.is_property_explicit("default_value")
                ):
                    if self_col.default_value != other_col.default_value:
                        if name not in column_differences:
                            column_differences[name] = {}
                        column_differences[name]["default_value"] = {
                            "self": self_col.default_value,
                            "other": other_col.default_value,
                        }

        if column_differences:
            differences["column_differences"] = column_differences

        # BACKLOG P3 (story 10-26): Ajouter comparaison des contraintes dans Table.compare_to()
        # Raison: Complexité de normalisation des noms de contraintes cross-dialecte (auto-générés vs explicites)
        # Impact: Le diff de schéma ne détecte pas les ajouts/suppressions de PK, FK, UNIQUE, CHECK
        # Approche: Comparer self.pk vs other.pk, self.foreign_keys vs other.foreign_keys, etc.
        #   Nécessite normalisation des noms (ignorer noms auto-générés dialecte-spécifiques)
        #   Attributs disponibles: pk, foreign_keys, unique_constraints, check_constraints
        #   (indexes sont trackés séparément via diff.missing_indexes / diff.extra_indexes)
        # Dépendances: Normalisation cross-dialecte des noms de contraintes à définir d'abord
        # Ref: voir _bmad-output/implementation-artifacts/10-26-todos-documenter-ou-implementer.md

        return differences

    def to_dict(self) -> Dict[str, Any]:
        """Convert table to dictionary representation.

        Returns:
            Dictionary with table attributes
        """
        return {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "columns": [
                {
                    "name": col.name,
                    "data_type": col.data_type,
                    "nullable": col.nullable,
                    "default_value": col.default_value,
                    "is_identity": getattr(col, "is_identity", False),
                    "identity_generation": getattr(col, "identity_generation", None),
                    "identity_seed": getattr(col, "identity_seed", None),
                    "identity_increment": getattr(col, "identity_increment", None),
                    "is_computed": getattr(col, "is_computed", False),
                    "computed_expression": getattr(col, "computed_expression", None),
                    "computed_stored": getattr(col, "computed_stored", False),
                    "comment": getattr(col, "comment", None),
                    "ordinal_position": getattr(col, "ordinal_position", None),
                    "collation": getattr(col, "collation", None),
                    "explicit_properties": getattr(col, "explicit_properties", {}),
                }
                for col in self.columns
            ],
            "constraints": [
                {
                    "name": c.name,
                    "constraint_type": c.constraint_type,
                    "columns": c.columns,
                    "reference_table": c.reference_table,
                    "reference_schema": c.reference_schema,
                    "reference_columns": c.reference_columns,
                    "check_expression": getattr(c, "check_expression", None),
                    "explicit_properties": getattr(c, "explicit_properties", {}),
                }
                for c in self.constraints
            ],
            "temporary": self.temporary,
            "tablespace": self.tablespace,
            "comment": self.comment,
            "storage_engine": self.storage_engine,
            "row_format": self.row_format,
            "table_collation": self.table_collation,
            "next_auto_increment": self.next_auto_increment,
            "create_options": self.create_options,
            "filegroup": self.filegroup,
            "memory_optimized": self.memory_optimized,
            "system_versioned": self.system_versioned,
            "history_table": self.history_table,
            "history_schema": self.history_schema,
            "period_start_column": self.period_start_column,
            "period_end_column": self.period_end_column,
            "partition_method": self.partition_method,
            "partition_columns": self.partition_columns,
            "partitions": (
                [partition.to_dict() for partition in self.partitions] if self.partitions else []
            ),
            "export_partitions": (
                [partition.to_dict() for partition in self.export_partitions]
                if self.export_partitions
                else []
            ),
            "derived_from": self.derived_from,
            "raw_ddl": self.raw_ddl,
            "metadata": self.metadata,
            "dialect_options": self.dialect_options,
            "explicit_properties": self.explicit_properties,
            "row_security": self.row_security,
            "force_row_security": self.force_row_security,
            "policies": self.policies,
            "pctfree": self.pctfree,
            "pctused": self.pctused,
            "initial": self.initial,
            "next": self.next,
            "inherits": self.inherits,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Table":
        """Create table from dictionary representation.

        Args:
            data: Dictionary with table attributes

        Returns:
            Table object
        """
        dialect = data.get("dialect")
        object_type_value = data.get("object_type", SqlObjectType.TABLE.value)
        if isinstance(object_type_value, SqlObjectType):
            object_type = object_type_value
        else:
            try:
                object_type = SqlObjectType(str(object_type_value))
            except ValueError:
                object_type = SqlObjectType.TABLE

        # Create columns
        columns = []
        for col_data in data.get("columns", []):
            col = SqlColumn(
                name=col_data["name"],
                data_type=col_data["data_type"],
                is_nullable=col_data.get("nullable", True),
                default_value=col_data.get("default_value"),
                is_identity=col_data.get("is_identity", False),
                identity_generation=col_data.get("identity_generation"),
                identity_seed=col_data.get("identity_seed"),
                identity_increment=col_data.get("identity_increment"),
                is_computed=col_data.get("is_computed", False),
                computed_expression=col_data.get("computed_expression"),
                computed_stored=col_data.get("computed_stored", False),
                comment=col_data.get("comment"),
                ordinal_position=col_data.get("ordinal_position"),
                collation=col_data.get("collation"),
                dialect=dialect,
            )
            # Restore explicit properties
            if col_data.get("explicit_properties"):
                for prop, is_explicit in col_data["explicit_properties"].items():
                    if is_explicit:
                        col.mark_property_explicit(prop)
            columns.append(col)

        # Create constraints
        constraints = []
        for c_data in data.get("constraints", []):
            constraint = SqlConstraint(
                name=c_data.get("name"),
                constraint_type=c_data["constraint_type"],
                column_names=c_data["columns"],
                reference_table=c_data.get("reference_table"),
                reference_columns=c_data.get("reference_columns"),
                check_expression=c_data.get("check_expression"),
                dialect=dialect,
            )
            constraint.reference_schema = c_data.get("reference_schema")
            # Restore explicit properties
            if c_data.get("explicit_properties"):
                for prop, is_explicit in c_data["explicit_properties"].items():
                    if is_explicit:
                        constraint.mark_property_explicit(prop)
            constraints.append(constraint)

        from core.sql_model.table_options import (
            MySqlTableOptions,
            OracleStorageOptions,
            PostgresTableOptions,
            SqlServerTableOptions,
            TableOptions,
        )

        options = TableOptions(
            mysql=MySqlTableOptions(
                storage_engine=data.get("storage_engine"),
                row_format=data.get("row_format"),
                table_collation=data.get("table_collation"),
                next_auto_increment=data.get("next_auto_increment"),
                create_options=data.get("create_options"),
            ),
            sqlserver=SqlServerTableOptions(
                filegroup=data.get("filegroup"),
                memory_optimized=data.get("memory_optimized", False),
                system_versioned=data.get("system_versioned", False),
                history_table=data.get("history_table"),
                history_schema=data.get("history_schema"),
                period_start_column=data.get("period_start_column"),
                period_end_column=data.get("period_end_column"),
            ),
            postgres=PostgresTableOptions(
                row_security=data.get("row_security", False),
                force_row_security=data.get("force_row_security", False),
                policies=data.get("policies") or [],
                inherits=data.get("inherits") or [],
            ),
            oracle_storage=OracleStorageOptions(
                pctfree=data.get("pctfree"),
                pctused=data.get("pctused"),
                initial=data.get("initial"),
                next=data.get("next"),
            ),
            derived_from=data.get("derived_from"),
            raw_ddl=data.get("raw_ddl"),
        )

        table = cls.from_options(
            name=data["name"],
            columns=columns,
            options=options,
            schema=data.get("schema"),
            constraints=constraints,
            temporary=data.get("temporary", False),
            tablespace=data.get("tablespace"),
            comment=data.get("comment"),
            object_type=object_type,
            dialect=dialect,
        )

        if data.get("partitions"):
            table.partitions = [Partition.from_dict(item) for item in data["partitions"]]
        if data.get("export_partitions"):
            table.export_partitions = [
                Partition.from_dict(item) for item in data["export_partitions"]
            ]
        table.partition_method = data.get("partition_method")
        table.partition_columns = data.get("partition_columns")
        table.metadata = data.get("metadata", {})
        # Merge — do NOT overwrite. ``from_options`` populated dialect_options
        # via the legacy flat-field aliases; restoring an explicit value here
        # (e.g. from a newer serialization that includes the dict directly)
        # must take precedence but absence must not wipe what was just set.
        for plugin, opts in (data.get("dialect_options") or {}).items():
            for key, value in opts.items():
                table.set_dialect_option(plugin, key, value)

        # Restore explicit properties
        if data.get("explicit_properties"):
            for prop, is_explicit in data["explicit_properties"].items():
                if is_explicit:
                    table.mark_property_explicit(prop)

        return table

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Table):
            return False
        return (
            self.name == other.name
            and self.schema == other.schema
            and self.temporary == other.temporary
            and self.tablespace == other.tablespace
            and self.dialect == other.dialect
            and self.columns == other.columns
            and self.constraints == other.constraints
            and self.filegroup == other.filegroup
            and self.memory_optimized == other.memory_optimized
            and self.system_versioned == other.system_versioned
            and self.history_table == other.history_table
            and self.history_schema == other.history_schema
            and self.period_start_column == other.period_start_column
            and self.period_end_column == other.period_end_column
            and self.row_security == other.row_security
            and self.force_row_security == other.force_row_security
            and self.policies == other.policies
            and self.storage_engine == other.storage_engine
            and self.row_format == other.row_format
            and self.table_collation == other.table_collation
            and self.next_auto_increment == other.next_auto_increment
            and self.object_type == other.object_type
            and self.raw_ddl == other.raw_ddl
            and self.create_options == other.create_options
            and self.partition_method == other.partition_method
            and self.partition_columns == other.partition_columns
            and self.partitions == other.partitions
            and self.comment == other.comment
            and self.inherits == other.inherits
            and self.derived_from == other.derived_from
            and self.pctfree == other.pctfree
            and self.pctused == other.pctused
            and self.initial == other.initial
            and self.next == other.next
            and self.export_partitions == other.export_partitions
            and self.dialect_options == other.dialect_options
        )
