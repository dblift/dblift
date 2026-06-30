"""Dialect-agnostic ``Table`` SQL object — columns, constraints, partitions, options."""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core.sql_model.base import (
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
)
from core.sql_model.partition import Partition

# ADR-26 E / story 26-5 — ``Table`` stores its built-in per-dialect options
# inside ``dialect_options`` under the owning plugin's canonical namespace
# (``mysql`` / ``sqlserver`` / ``postgresql`` / ``oracle``), the same public
# extension point third-party plugins use. Those namespace strings are resolved
# from the plugin registry via ``core.sql_model.table_options`` so this module
# names no dialect. Framework consumers read built-ins via
# ``get_dialect_option(<canonical-dialect>, "<option>")`` (resolving the
# canonical dialect from the target ``quirks`` already in scope), not named
# convenience properties.

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
        the dialect subset without going through the kwargs surface. Built-in
        options land in ``dialect_options`` under their canonical namespace
        (resolved from the plugin registry, so no dialect literal is named).
        """
        from core.sql_model.table_options import builtin_namespace_for

        ns_mysql = builtin_namespace_for("table_uses_storage_engine_clause")
        ns_sqlserver = builtin_namespace_for("table_uses_filegroup_syntax")
        ns_postgres = builtin_namespace_for("table_supports_inherits")
        ns_oracle = builtin_namespace_for("table_supports_storage_params")

        # MySQL
        if ns_mysql:
            self._set_plugin_option(ns_mysql, "storage_engine", opts.mysql.storage_engine)
            self._set_plugin_option(ns_mysql, "row_format", opts.mysql.row_format)
            self._set_plugin_option(ns_mysql, "table_collation", opts.mysql.table_collation)
            self._set_plugin_option(ns_mysql, "next_auto_increment", opts.mysql.next_auto_increment)
            self._set_plugin_option(ns_mysql, "create_options", opts.mysql.create_options)
        # SQL Server
        if ns_sqlserver:
            self._set_plugin_option(ns_sqlserver, "filegroup", opts.sqlserver.filegroup)
            self._set_plugin_option(
                ns_sqlserver, "memory_optimized", opts.sqlserver.memory_optimized, default=False
            )
            self._set_plugin_option(
                ns_sqlserver, "system_versioned", opts.sqlserver.system_versioned, default=False
            )
            self._set_plugin_option(ns_sqlserver, "history_table", opts.sqlserver.history_table)
            self._set_plugin_option(ns_sqlserver, "history_schema", opts.sqlserver.history_schema)
            self._set_plugin_option(
                ns_sqlserver, "period_start_column", opts.sqlserver.period_start_column
            )
            self._set_plugin_option(
                ns_sqlserver, "period_end_column", opts.sqlserver.period_end_column
            )
        # PostgreSQL
        if ns_postgres:
            self._set_plugin_option(
                ns_postgres, "row_security", opts.postgres.row_security, default=False
            )
            self._set_plugin_option(
                ns_postgres, "force_row_security", opts.postgres.force_row_security, default=False
            )
            self._set_plugin_option(
                ns_postgres, "policies", list(opts.postgres.policies), default=[]
            )
            self._set_plugin_option(
                ns_postgres, "inherits", list(opts.postgres.inherits), default=[]
            )
        # Oracle / DB2 storage
        if ns_oracle:
            self._set_plugin_option(ns_oracle, "pctfree", opts.oracle_storage.pctfree)
            self._set_plugin_option(ns_oracle, "pctused", opts.oracle_storage.pctused)
            self._set_plugin_option(ns_oracle, "initial", opts.oracle_storage.initial)
            self._set_plugin_option(ns_oracle, "next", opts.oracle_storage.next)
        # Misc
        self.derived_from = opts.derived_from
        self.raw_ddl = opts.raw_ddl

        # Track explicit T-SQL-specific properties for diff sensitivity
        sqlserver_opts = self.dialect_options.get(ns_sqlserver, {}) if ns_sqlserver else {}
        if sqlserver_opts.get("filegroup") is not None:
            self.mark_property_explicit("filegroup")
        if sqlserver_opts.get("memory_optimized"):
            self.mark_property_explicit("memory_optimized")
        if sqlserver_opts.get("system_versioned"):
            self.mark_property_explicit("system_versioned")
        if sqlserver_opts.get("history_table") is not None:
            self.mark_property_explicit("history_table")
        if sqlserver_opts.get("history_schema") is not None:
            self.mark_property_explicit("history_schema")
        if sqlserver_opts.get("period_start_column") is not None:
            self.mark_property_explicit("period_start_column")
        if sqlserver_opts.get("period_end_column") is not None:
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
            builtin_namespace_for,
        )

        ns_mysql = builtin_namespace_for("table_uses_storage_engine_clause")
        ns_sqlserver = builtin_namespace_for("table_uses_filegroup_syntax")
        ns_postgres = builtin_namespace_for("table_supports_inherits")
        ns_oracle = builtin_namespace_for("table_supports_storage_params")

        def _opt(namespace: Optional[str], key: str, default: Any = None) -> Any:
            if not namespace:
                return default
            return self.get_dialect_option(namespace, key, default=default)

        return TableOptions(
            mysql=MySqlTableOptions(
                storage_engine=_opt(ns_mysql, "storage_engine"),
                row_format=_opt(ns_mysql, "row_format"),
                table_collation=_opt(ns_mysql, "table_collation"),
                next_auto_increment=_opt(ns_mysql, "next_auto_increment"),
                create_options=_opt(ns_mysql, "create_options"),
            ),
            sqlserver=SqlServerTableOptions(
                filegroup=_opt(ns_sqlserver, "filegroup"),
                memory_optimized=bool(_opt(ns_sqlserver, "memory_optimized", default=False)),
                system_versioned=bool(_opt(ns_sqlserver, "system_versioned", default=False)),
                history_table=_opt(ns_sqlserver, "history_table"),
                history_schema=_opt(ns_sqlserver, "history_schema"),
                period_start_column=_opt(ns_sqlserver, "period_start_column"),
                period_end_column=_opt(ns_sqlserver, "period_end_column"),
            ),
            postgres=PostgresTableOptions(
                row_security=bool(_opt(ns_postgres, "row_security", default=False)),
                force_row_security=bool(_opt(ns_postgres, "force_row_security", default=False)),
                policies=list(_opt(ns_postgres, "policies", default=[]) or []),
                inherits=list(_opt(ns_postgres, "inherits", default=[]) or []),
            ),
            oracle_storage=OracleStorageOptions(
                pctfree=_opt(ns_oracle, "pctfree"),
                pctused=_opt(ns_oracle, "pctused"),
                initial=_opt(ns_oracle, "initial"),
                next=_opt(ns_oracle, "next"),
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
        """OSS builds do not ship dialect-specific ALTER TABLE generators."""
        return []

    def generate_alter_table_self_referencing_foreign_keys(self) -> List[str]:
        """OSS builds do not ship dialect-specific ALTER TABLE generators."""
        return []

    @property
    def create_statement(self) -> str:
        """Generate a basic CREATE TABLE statement in OSS builds."""
        table_name = self.format_identifier(self.name)
        if self.schema:
            table_name = f"{self.format_identifier(self.schema)}.{table_name}"

        definitions = []
        primary_key_columns = []
        for column in self.columns:
            column_def = f"{self.format_identifier(column.name)} {column.data_type}"
            default_value = getattr(column, "default_value", None)
            if default_value is not None:
                column_def += f" DEFAULT {default_value}"
            if not getattr(column, "nullable", True) or getattr(column, "is_primary_key", False):
                column_def += " NOT NULL"
            definitions.append(column_def)
            if getattr(column, "is_primary_key", False):
                primary_key_columns.append(column.name)

        if primary_key_columns and not any(
            getattr(c.constraint_type, "value", str(c.constraint_type)) == "PRIMARY KEY"
            for c in self.constraints
        ):
            columns = ", ".join(self.format_identifier(c) for c in primary_key_columns)
            definitions.append(f"PRIMARY KEY ({columns})")

        for constraint in self.constraints:
            constraint_type = getattr(
                constraint.constraint_type, "value", str(constraint.constraint_type)
            )
            columns = ", ".join(self.format_identifier(c) for c in (constraint.column_names or []))
            prefix = (
                f"CONSTRAINT {self.format_identifier(constraint.name)} " if constraint.name else ""
            )
            if constraint_type in {"PRIMARY KEY", "UNIQUE"}:
                definitions.append(f"{prefix}{constraint_type} ({columns})")
            elif constraint_type == "CHECK" and constraint.check_expression:
                definitions.append(f"{prefix}CHECK ({constraint.check_expression})")
            elif constraint_type == "FOREIGN KEY" and constraint.reference_table:
                reference = self.format_identifier(constraint.reference_table)
                ref_columns = ", ".join(
                    self.format_identifier(c) for c in (constraint.reference_columns or [])
                )
                clause = f"{prefix}FOREIGN KEY ({columns}) REFERENCES {reference}"
                if ref_columns:
                    clause += f" ({ref_columns})"
                if constraint.on_delete:
                    clause += f" ON DELETE {constraint.on_delete}"
                if constraint.on_update:
                    clause += f" ON UPDATE {constraint.on_update}"
                definitions.append(clause)

        body = ",\n    ".join(definitions)
        return f"CREATE TABLE {table_name} (\n    {body}\n);"

    @property
    def drop_statement(self) -> str:
        """Generate a basic DROP TABLE statement in OSS builds."""
        table_name = self.format_identifier(self.name)
        if self.schema:
            table_name = f"{self.format_identifier(self.schema)}.{table_name}"
        return f"DROP TABLE IF EXISTS {table_name};"

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
        # Story 26-5: gate via plugin Quirks (``table_uses_filegroup_syntax``)
        # and read the built-ins from ``dialect_options`` under the canonical
        # SQL Server namespace resolved from the registry (no dialect literal).
        from core.sql_model.table_options import builtin_namespace_for
        from db.provider_registry import ProviderRegistry

        ns_sqlserver = builtin_namespace_for("table_uses_filegroup_syntax")

        def _filegroup_supported(dialect_name: Optional[str]) -> bool:
            if not dialect_name:
                return False
            canonical = ProviderRegistry.canonical_dialect_name(dialect_name)
            if not canonical:
                return False
            return ProviderRegistry.get_quirks(canonical).table_uses_filegroup_syntax

        def _ss(table_obj: "Table", key: str, default: Any = None) -> Any:
            if not ns_sqlserver:
                return default
            return table_obj.get_dialect_option(ns_sqlserver, key, default=default)

        if _filegroup_supported(self.dialect) or _filegroup_supported(other_table.dialect):
            if self.is_property_explicit("filegroup") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("filegroup")
            ):
                if _ss(self, "filegroup") != _ss(other_table, "filegroup"):
                    differences["filegroup"] = {
                        "self": _ss(self, "filegroup"),
                        "other": _ss(other_table, "filegroup"),
                    }

            # Compare memory-optimized property
            if self.is_property_explicit("memory_optimized") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("memory_optimized")
            ):
                self_mem = bool(_ss(self, "memory_optimized", default=False))
                other_mem = bool(_ss(other_table, "memory_optimized", default=False))
                if self_mem != other_mem:
                    differences["memory_optimized"] = {
                        "self": self_mem,
                        "other": other_mem,
                    }

            # Compare system-versioned property
            self_sysver = bool(_ss(self, "system_versioned", default=False))
            other_sysver = bool(_ss(other_table, "system_versioned", default=False))
            if self.is_property_explicit("system_versioned") or (
                hasattr(other_table, "is_property_explicit")
                and other_table.is_property_explicit("system_versioned")
            ):
                if self_sysver != other_sysver:
                    differences["system_versioned"] = {
                        "self": self_sysver,
                        "other": other_sysver,
                    }
                # Also compare history table if system-versioned
                if self_sysver and other_sysver:
                    if _ss(self, "history_table") != _ss(other_table, "history_table"):
                        differences["history_table"] = {
                            "self": _ss(self, "history_table"),
                            "other": _ss(other_table, "history_table"),
                        }
                    if _ss(self, "history_schema") != _ss(other_table, "history_schema"):
                        differences["history_schema"] = {
                            "self": _ss(self, "history_schema"),
                            "other": _ss(other_table, "history_schema"),
                        }
                    if _ss(self, "period_start_column") != _ss(other_table, "period_start_column"):
                        differences["period_start_column"] = {
                            "self": _ss(self, "period_start_column"),
                            "other": _ss(other_table, "period_start_column"),
                        }
                    if _ss(self, "period_end_column") != _ss(other_table, "period_end_column"):
                        differences["period_end_column"] = {
                            "self": _ss(self, "period_end_column"),
                            "other": _ss(other_table, "period_end_column"),
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
            # Built-in per-dialect options (storage_engine / filegroup /
            # pctfree / row_security / ...) live exclusively inside
            # ``dialect_options`` under their canonical namespace — the public
            # extension point — and are no longer mirrored as redundant
            # top-level keys (ADR-26 E story 26-5).
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
        # All built-in per-dialect options (filegroup / storage_engine /
        # pctfree / row_security / inherits / ...) live inside
        # ``dialect_options``, so the single ``dialect_options`` comparison
        # covers every one of them — no need to enumerate each built-in
        # (ADR-26 E story 26-5).
        return (
            self.name == other.name
            and self.schema == other.schema
            and self.temporary == other.temporary
            and self.tablespace == other.tablespace
            and self.dialect == other.dialect
            and self.columns == other.columns
            and self.constraints == other.constraints
            and self.object_type == other.object_type
            and self.raw_ddl == other.raw_ddl
            and self.partition_method == other.partition_method
            and self.partition_columns == other.partition_columns
            and self.partitions == other.partitions
            and self.comment == other.comment
            and self.derived_from == other.derived_from
            and self.export_partitions == other.export_partitions
            and self.dialect_options == other.dialect_options
        )
