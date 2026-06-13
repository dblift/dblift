"""SQL Statement Generator for converting diffs to SQL.

This module converts schema diffs into executable SQL statements
with dialect-specific syntax.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Type, cast

from core.comparison.diff_models import (
    SchemaDiff,
    TableDiff,
)
from core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory
from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.diff_converters.column_converter import ColumnConverter
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.sql_generator.sql_statement import GenerationOptions, SqlStatement
from core.sql_model.base import SqlColumn
from core.sql_model.database_link import DatabaseLink
from core.sql_model.dialect import DialectEnum
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.linked_server import LinkedServer
from core.sql_model.module import Module
from core.sql_model.package import Package
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View


class _ObjectTypeSpec(NamedTuple):
    """Registry entry describing how to generate SQL for a schema object type."""

    object_type: str
    object_class: Type
    diff_missing_attr: str
    diff_extra_attr: str
    diff_modified_attr: str
    expected_attr: str
    supports_create_or_replace: bool
    dummy_kwargs: Dict[str, Any]


_OBJECT_TYPE_SPECS: List[_ObjectTypeSpec] = [
    _ObjectTypeSpec(
        "VIEW", View, "missing_views", "extra_views", "modified_views", "views", True, {}
    ),
    _ObjectTypeSpec(
        "INDEX",
        Index,
        "missing_indexes",
        "extra_indexes",
        "modified_indexes",
        "indexes",
        False,
        {"table_name": "dummy", "columns": []},
    ),
    _ObjectTypeSpec(
        "SEQUENCE",
        Sequence,
        "missing_sequences",
        "extra_sequences",
        "modified_sequences",
        "sequences",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "TRIGGER",
        Trigger,
        "missing_triggers",
        "extra_triggers",
        "modified_triggers",
        "triggers",
        False,
        {"table_name": "dummy"},
    ),
    _ObjectTypeSpec(
        "PROCEDURE",
        Procedure,
        "missing_procedures",
        "extra_procedures",
        "modified_procedures",
        "procedures",
        True,
        {},
    ),
    _ObjectTypeSpec(
        "FUNCTION",
        Procedure,
        "missing_functions",
        "extra_functions",
        "modified_functions",
        "functions",
        True,
        {"is_function": True},
    ),
    _ObjectTypeSpec(
        "SYNONYM",
        Synonym,
        "missing_synonyms",
        "extra_synonyms",
        "modified_synonyms",
        "synonyms",
        True,
        {"target_object": "dummy"},
    ),
    _ObjectTypeSpec(
        "EXTENSION",
        Extension,
        "missing_extensions",
        "extra_extensions",
        "modified_extensions",
        "extensions",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "TYPE",
        UserDefinedType,
        "missing_user_defined_types",
        "extra_user_defined_types",
        "modified_user_defined_types",
        "user_defined_types",
        False,
        {"type_category": "ENUM"},
    ),
    _ObjectTypeSpec(
        "PACKAGE",
        Package,
        "missing_packages",
        "extra_packages",
        "modified_packages",
        "packages",
        True,
        {},
    ),
    _ObjectTypeSpec(
        "EVENT",
        Event,
        "missing_events",
        "extra_events",
        "modified_events",
        "events",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "DATABASE_LINK",
        DatabaseLink,
        "missing_database_links",
        "extra_database_links",
        "modified_database_links",
        "database_links",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "LINKED_SERVER",
        LinkedServer,
        "missing_linked_servers",
        "extra_linked_servers",
        "modified_linked_servers",
        "linked_servers",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "MODULE",
        Module,
        "missing_modules",
        "extra_modules",
        "modified_modules",
        "modules",
        True,
        {"definition": ""},
    ),
    _ObjectTypeSpec(
        "FOREIGN_DATA_WRAPPER",
        ForeignDataWrapper,
        "missing_foreign_data_wrappers",
        "extra_foreign_data_wrappers",
        "modified_foreign_data_wrappers",
        "foreign_data_wrappers",
        False,
        {},
    ),
    _ObjectTypeSpec(
        "FOREIGN_SERVER",
        ForeignServer,
        "missing_foreign_servers",
        "extra_foreign_servers",
        "modified_foreign_servers",
        "foreign_servers",
        False,
        {"fdw_name": "dummy"},
    ),
]

_OBJECT_TYPE_SPECS_BY_TYPE: Dict[str, _ObjectTypeSpec] = {
    spec.object_type: spec for spec in _OBJECT_TYPE_SPECS
}


@dataclass
class DiffGenerationContext:
    """Expected schema objects for SQL generation from a diff.

    Groups the 17 optional expected_* dictionaries of DiffSqlGenerator.generate_from_diff()
    to simplify the method signature.
    """

    # Table objects
    expected_tables: Optional[Dict[str, Table]] = None
    # View objects
    expected_views: Optional[Dict[str, View]] = None
    # Index and sequence objects
    expected_indexes: Optional[Dict[str, Index]] = None
    expected_sequences: Optional[Dict[str, Sequence]] = None
    # Trigger/procedure/function objects
    expected_triggers: Optional[Dict[str, Trigger]] = None
    expected_procedures: Optional[Dict[str, Procedure]] = None
    expected_functions: Optional[Dict[str, Procedure]] = None
    # Synonym/extension/type objects
    expected_synonyms: Optional[Dict[str, Synonym]] = None
    expected_extensions: Optional[Dict[str, Extension]] = None
    expected_user_defined_types: Optional[Dict[str, UserDefinedType]] = None
    # Package/event objects
    expected_packages: Optional[Dict[str, Package]] = None
    expected_events: Optional[Dict[str, Event]] = None
    # Module objects (DB2-specific)
    expected_modules: Optional[Dict[str, Module]] = None
    # Link/wrapper/server objects
    expected_database_links: Optional[Dict[str, DatabaseLink]] = None
    expected_linked_servers: Optional[Dict[str, LinkedServer]] = None
    expected_foreign_data_wrappers: Optional[Dict[str, ForeignDataWrapper]] = None
    expected_foreign_servers: Optional[Dict[str, ForeignServer]] = None


def _ensure_semicolon(sql: str) -> str:
    """Ensure the SQL statement ends with a semicolon."""
    return sql if sql.endswith(";") else sql + ";"


class DiffSqlStatementBuilder:
    """Builds individual DDL SQL statements (CREATE / ALTER / DROP).

    This class is responsible solely for translating a single schema object
    (or object-type spec) into a :class:`~core.sql_generator.sql_statement.SqlStatement`.
    It has no knowledge of *which* objects changed or in what order to emit SQL —
    that orchestration belongs to :class:`DiffSqlGenerator`.

    Extracted from ``DiffSqlGenerator`` (story 25-17 SRP-04) to separate
    DDL building from diff orchestration.
    """

    def __init__(
        self,
        dialect: str,
        sql_generator: BaseSqlGenerator,
        alter_generator: Any,
        column_converter: ColumnConverter,
    ) -> None:
        """Wire dialect plus the collaborators that emit CREATE/ALTER DDL for individual objects."""
        self.dialect = dialect
        self.sql_generator = sql_generator
        self.alter_generator = alter_generator
        self.column_converter = column_converter
        self.logger = logging.getLogger(__name__)

    # ── Dialect classification ────────────────────────────────────────

    def _is_nosql_dialect(self) -> bool:
        """Return True if ``self.dialect`` is a NoSQL dialect (e.g. Cosmos DB).

        Queries :meth:`ProviderRegistry.get_quirks` at call time rather than
        reading the module-level ``NOSQL_DIALECTS`` frozenset. The frozenset
        is bound at import time and ends up empty in test contexts where
        plugin discovery has not yet been triggered — that produced the bug
        fixed alongside this helper where ``build_create_table_sql`` skipped
        the ``CREATE CONTAINER`` branch for cosmosdb and emitted a malformed
        ``CREATE CONTAINER container1 ();`` via the legacy ``create_statement``
        property fallback. ``ProviderRegistry.get_quirks`` self-discovers
        plugins on first call, so this stays correct regardless of import
        order.
        """
        from db.provider_registry import ProviderRegistry

        return bool(ProviderRegistry.get_quirks(self.dialect).is_nosql)

    # ── Identifier helpers ────────────────────────────────────────────

    def quote_identifier(self, identifier: str) -> str:
        """Quote identifier based on dialect.

        Delegates to DialectEnum.quote_identifier (story 21-14 dispatch).
        """
        return DialectEnum.quote_identifier(self.dialect, identifier)

    def parse_table_name(self, table_name: str) -> Tuple[Optional[str], str]:
        """Parse table name into (schema, name)."""
        if "." in table_name:
            parts = table_name.split(".", 1)
            return parts[0], parts[1]
        return None, table_name

    def format_identifier(self, schema: Optional[str], name: str) -> str:
        """Format schema-qualified identifier."""
        if schema:
            return f"{self.quote_identifier(schema)}.{self.quote_identifier(name)}"
        return self.quote_identifier(name)

    # ── Generic object-type DDL ───────────────────────────────────────

    def build_create_sql(
        self,
        spec: _ObjectTypeSpec,
        obj: Any,
        options: GenerationOptions,
    ) -> Optional[SqlStatement]:
        """Generate a CREATE statement for any registry object type."""
        try:
            sql = self.sql_generator.generate_create_statement(obj)
            sql = _ensure_semicolon(sql)
            return SqlStatement(
                sql=sql,
                statement_type="CREATE",
                object_type=spec.object_type,
                object_name=obj.name,
                dialect=self.dialect,
            )
        except Exception as e:
            self.logger.warning(f"Failed to generate CREATE {spec.object_type} for {obj.name}: {e}")
            return None

    def build_create_or_replace_sql(
        self,
        spec: _ObjectTypeSpec,
        obj: Any,
        options: GenerationOptions,
    ) -> Optional[SqlStatement]:
        """Generate a CREATE OR REPLACE statement for types that support it."""
        try:
            sql = self.sql_generator.generate_create_statement(obj)
            if sql.upper().startswith("CREATE ") and not sql.upper().startswith(
                "CREATE OR REPLACE "
            ):
                sql = sql.replace("CREATE ", "CREATE OR REPLACE ", 1)
            sql = _ensure_semicolon(sql)
            return SqlStatement(
                sql=sql,
                statement_type="CREATE",
                object_type=spec.object_type,
                object_name=obj.name,
                dialect=self.dialect,
            )
        except Exception as e:
            self.logger.warning(
                f"Failed to generate CREATE OR REPLACE {spec.object_type} for {obj.name}: {e}"
            )
            return None

    def build_drop_sql(
        self,
        spec: _ObjectTypeSpec,
        obj_name: str,
        options: GenerationOptions,
    ) -> Optional[SqlStatement]:
        """Generate a DROP statement for any registry object type."""
        try:
            parts = obj_name.split(".")
            dummy = spec.object_class(name=parts[-1], **spec.dummy_kwargs)
            if len(parts) > 1:
                dummy.schema = parts[0]
            sql = self.sql_generator._generate_drop_statement(dummy, self.dialect)
            sql = _ensure_semicolon(sql)
            return SqlStatement(
                sql=sql,
                statement_type="DROP",
                object_type=spec.object_type,
                object_name=obj_name,
                dialect=self.dialect,
            )
        except Exception as e:
            self.logger.warning(f"Failed to generate DROP {spec.object_type} for {obj_name}: {e}")
            return None

    # ── Table DDL ────────────────────────────────────────────────────

    def build_create_table_sql(
        self, table: Table, options: GenerationOptions
    ) -> Optional[SqlStatement]:
        """Generate CREATE TABLE statement."""
        if self._is_nosql_dialect():
            schema, name = self.parse_table_name(
                f"{table.schema}.{table.name}" if table.schema else table.name
            )
            container_name = self.quote_identifier(name)
            partition_key = "/id"
            if hasattr(table, "metadata") and isinstance(table.metadata, dict):
                partition_key = table.metadata.get("partition_key", partition_key)
            sql = (
                f"CREATE CONTAINER {container_name} (id STRING) "
                f"WITH (partitionKey='{partition_key}')"
            )
            sql = _ensure_semicolon(sql)
        elif hasattr(table, "create_statement") and table.create_statement:
            sql = table.create_statement
            sql = _ensure_semicolon(sql)
        else:
            schema, name = self.parse_table_name(
                f"{table.schema}.{table.name}" if table.schema else table.name
            )
            formatted_table = self.format_identifier(schema, name)
            column_defs = [self.format_column_definition(col) for col in table.columns]
            sql = f"CREATE TABLE {formatted_table} (\n    "
            sql += ",\n    ".join(column_defs)
            sql += "\n);"

        return SqlStatement(
            sql=sql,
            statement_type="CREATE",
            object_type="TABLE",
            object_name=table.name,
            dialect=self.dialect,
        )

    def build_drop_table_sql(
        self, table_name: str, options: GenerationOptions
    ) -> Optional[SqlStatement]:
        """Generate DROP TABLE statement using SQL generator."""
        dummy_table = Table(name=table_name.split(".")[-1])
        if "." in table_name:
            dummy_table.schema = table_name.split(".")[0]

        try:
            sql = self.sql_generator._generate_drop_statement(dummy_table, self.dialect)
            sql = _ensure_semicolon(sql)

            requires_sdk = False
            sdk_operation = None
            if self._is_nosql_dialect() and "DROP CONTAINER" in sql.upper():
                requires_sdk = True
                container_name = table_name.split(".")[-1]
                sdk_operation = {
                    "operation": "delete_container",
                    "container_name": container_name,
                    "python_code": (f"database.delete_container(container='{container_name}')"),
                    "warning": "This will DELETE ALL DATA in the container",
                }

            return SqlStatement(
                sql=sql,
                statement_type="DROP",
                object_type="TABLE",
                object_name=table_name,
                dialect=self.dialect,
                requires_sdk=requires_sdk,
                sdk_operation=sdk_operation,
            )
        except Exception as e:
            self.logger.warning(f"Failed to generate DROP TABLE for {table_name}: {e}")
            return None

    def build_drop_index_sql(
        self,
        index_name: str,
        table_name: Optional[str],
        options: GenerationOptions,
    ) -> Optional[SqlStatement]:
        """Generate DROP INDEX statement using SQL generator."""
        dummy_index = Index(
            name=index_name.split(".")[-1],
            table_name=table_name or "dummy",
            columns=[],
        )
        if "." in index_name:
            dummy_index.schema = index_name.split(".")[0]

        try:
            sql = self.sql_generator._generate_drop_statement(dummy_index, self.dialect)
            sql = _ensure_semicolon(sql)
            return SqlStatement(
                sql=sql,
                statement_type="DROP",
                object_type="INDEX",
                object_name=index_name,
                dialect=self.dialect,
            )
        except Exception as e:
            self.logger.warning(f"Failed to generate DROP INDEX for {index_name}: {e}")
            return None

    def format_column_definition(self, column: SqlColumn) -> str:
        """Format column definition for CREATE/ALTER statements."""
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect)
        parts = [column.data_type]

        if column.collation and quirks.table_supports_inline_collate:
            # PG quotes the collation name; MySQL doesn't. quote_identifier is dialect-aware.
            parts.append(f"COLLATE {self.quote_identifier(column.collation)}")

        # Only add NOT NULL when explicitly False; nullable=None (unknown) must not
        # be treated as NOT NULL.
        if column.nullable is False:
            parts.append("NOT NULL")

        if column.default_value:
            default_val = quirks.unwrap_default_value(str(column.default_value).strip(), column)
            parts.append(f"DEFAULT {default_val}")

        if column.is_identity:
            identity_clause = quirks.render_identity_clause(column)
            if identity_clause:
                parts.append(identity_clause)

        if column.is_computed and column.computed_expression:
            # ``render_computed_column`` returns ``(suffix, new_parts0)``. PG/MySQL/Oracle
            # encode the full clause in ``suffix`` (``GENERATED ALWAYS AS (expr) STORED``).
            # SQL Server uses ``new_parts0`` (``"col_name AS (expr)"``) which is meant to
            # replace the ``col_name col_type`` prefix in the table-DDL generator; here we
            # strip the leading ``col_name`` and append the remainder so the diff-path
            # emits the historical ``AS (expr) [PERSISTED]`` tail.
            formatted_name = self.quote_identifier(column.name)
            suffix_clause, new_parts0 = quirks.render_computed_column(column, formatted_name)
            if new_parts0 is not None:
                prefix = f"{formatted_name} "
                tail = new_parts0[len(prefix) :] if new_parts0.startswith(prefix) else new_parts0
                combined = f"{tail} {suffix_clause}".strip() if suffix_clause else tail
                parts.append(combined)
            elif suffix_clause:
                parts.append(suffix_clause)

        return " ".join(parts)


class DiffSqlGenerator:
    """Orchestrates SQL statement generation from schema diffs.

    This class decides *which* objects need SQL and in what order, delegating
    the actual DDL string construction to :class:`DiffSqlStatementBuilder`.
    """

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string
        """Initialize the SQL generator.

        Args:
            dialect: SQL dialect identifier to use for generation.
                Defaults to ``""`` so the framework never assumes a
                dialect when callers haven't supplied one — quirks
                lookups against an empty string fall back to
                ``BaseQuirks`` defaults.
        """
        self.dialect = (
            dialect.lower()
        )  # Normalized once here; all downstream code assumes lowercase
        self.logger = logging.getLogger(__name__)

        # Initialize converters
        self.column_converter = ColumnConverter(self.dialect)

        # Initialize SQL generator for CREATE/DROP statements
        self.sql_generator = cast(BaseSqlGenerator, SqlGeneratorFactory.create(self.dialect))

        # Initialize ALTER generator for ALTER TABLE statements
        self.alter_generator = AlterGeneratorFactory.create_generator(self.dialect)

        # DDL builder — handles all SQL string construction
        self.builder = DiffSqlStatementBuilder(
            dialect=self.dialect,
            sql_generator=self.sql_generator,
            alter_generator=self.alter_generator,
            column_converter=self.column_converter,
        )

    # ── Backward-compatible shims (delegate to builder) ──────────────
    # These thin wrappers preserve the existing private API so that
    # any external test or subclass that calls e.g. self._generate_create_table()
    # continues to work without modification.

    def _generate_create_for_type(self, spec, obj, options):
        return self.builder.build_create_sql(spec, obj, options)

    def _generate_create_or_replace_for_type(self, spec, obj, options):
        return self.builder.build_create_or_replace_sql(spec, obj, options)

    def _generate_drop_for_type(self, spec, obj_name, options):
        return self.builder.build_drop_sql(spec, obj_name, options)

    def _generate_create_table(self, table, options):
        return self.builder.build_create_table_sql(table, options)

    def _generate_drop_table(self, table_name, options):
        return self.builder.build_drop_table_sql(table_name, options)

    def _generate_drop_index(self, index_name, table_name, options):
        return self.builder.build_drop_index_sql(index_name, table_name, options)

    def _format_column_definition(self, column):
        return self.builder.format_column_definition(column)

    def _parse_table_name(self, table_name):
        return self.builder.parse_table_name(table_name)

    def _format_identifier(self, schema, name):
        return self.builder.format_identifier(schema, name)

    def _quote_identifier(self, identifier):
        return self.builder.quote_identifier(identifier)

    # ── Generic data-driven orchestration ────────────────────────────

    def _generate_statements_for_type(
        self,
        spec: _ObjectTypeSpec,
        diff: SchemaDiff,
        expected_objects: Dict[str, Any],
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Generate CREATE/DROP/COR statements for one object type."""
        statements: List[SqlStatement] = []

        # CREATE for missing objects
        for obj_name in getattr(diff, spec.diff_missing_attr, []):
            if obj_name in expected_objects:
                stmt = self.builder.build_create_sql(spec, expected_objects[obj_name], options)
                if stmt:
                    statements.append(stmt)
            else:
                self.logger.warning(
                    f"CREATE {spec.object_type} for {obj_name} skipped "
                    f"- expected definition not provided"
                )

        # CREATE OR REPLACE / CREATE for modified objects
        for obj_diff in getattr(diff, spec.diff_modified_attr, []):
            obj_name = getattr(obj_diff, "object_name", None) or getattr(obj_diff, "name", None)
            if obj_name and obj_name not in expected_objects:
                self.logger.warning(
                    f"CREATE OR REPLACE {spec.object_type} for {obj_name} skipped "
                    f"- expected definition not provided"
                )
            if obj_name and obj_name in expected_objects:
                if spec.supports_create_or_replace:
                    stmt = self.builder.build_create_or_replace_sql(
                        spec, expected_objects[obj_name], options
                    )
                else:
                    stmt = self.builder.build_create_sql(spec, expected_objects[obj_name], options)
                if stmt:
                    statements.append(stmt)

        # DROP for extra objects
        for obj_name in getattr(diff, spec.diff_extra_attr, []):
            stmt = self.builder.build_drop_sql(spec, obj_name, options)
            if stmt:
                statements.append(stmt)

        return statements

    # ── Main entry point ─────────────────────────────────────────────

    def generate_from_diff(
        self,
        diff: SchemaDiff,
        context: Optional[DiffGenerationContext] = None,
        options: Optional[GenerationOptions] = None,
    ) -> List[SqlStatement]:
        """Generate SQL statements from diff.

        Reads as four named phases applied in order:
        1. Modified tables → :meth:`_generate_table_changes` per table.
        2. Missing tables → ``CREATE TABLE`` (or warning if expected def absent).
        3. Extra tables → ``DROP TABLE``.
        4. Non-table object types → data-driven loop over
           :data:`_OBJECT_TYPE_SPECS` (16 types: views, indexes,
           sequences, triggers, procedures, functions, synonyms,
           extensions, user_defined_types, packages, events,
           database_links, linked_servers, foreign_data_wrappers,
           foreign_servers).
        """
        if context is None:
            context = DiffGenerationContext()
        if options is None:
            options = GenerationOptions(dialect=self.dialect)

        statements: List[SqlStatement] = []
        statements.extend(self._apply_modified_tables(diff, context, options))
        statements.extend(self._apply_missing_tables(diff, context, options))
        statements.extend(self._apply_extra_tables(diff, options))
        statements.extend(self._apply_typed_object_changes(diff, context, options))
        return statements

    def _apply_modified_tables(
        self,
        diff: SchemaDiff,
        context: DiffGenerationContext,
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Phase 1: emit per-table ``ALTER`` / ``CREATE OR REPLACE`` statements."""
        statements: List[SqlStatement] = []
        for table_diff in diff.modified_tables:
            statements.extend(
                self._generate_table_changes(table_diff, context.expected_tables, options)
            )
        return statements

    def _apply_missing_tables(
        self,
        diff: SchemaDiff,
        context: DiffGenerationContext,
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Phase 2: emit ``CREATE TABLE`` for every table missing in the live schema.

        Tables without an expected definition log a warning and are
        skipped — the operator must rerun with ``--expected-tables``
        populated to materialise them.
        """
        statements: List[SqlStatement] = []
        for table_name in diff.missing_tables:
            if context.expected_tables and table_name in context.expected_tables:
                create_stmt = self.builder.build_create_table_sql(
                    context.expected_tables[table_name], options
                )
                if create_stmt:
                    statements.append(create_stmt)
            else:
                self.logger.warning(
                    f"CREATE TABLE for {table_name} skipped "
                    f"- expected table definition not provided"
                )
        return statements

    def _apply_extra_tables(
        self,
        diff: SchemaDiff,
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Phase 3: emit ``DROP TABLE`` for every table that exists live but is unmanaged."""
        statements: List[SqlStatement] = []
        for table_name in diff.extra_tables:
            drop_stmt = self.builder.build_drop_table_sql(table_name, options)
            if drop_stmt:
                statements.append(drop_stmt)
        return statements

    def _apply_typed_object_changes(
        self,
        diff: SchemaDiff,
        context: DiffGenerationContext,
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Phase 4: data-driven generation for all 16 non-table object types.

        Each entry in :data:`_OBJECT_TYPE_SPECS` describes one object
        type (views, indexes, …); this helper looks up the matching
        ``expected_*`` map on ``context`` and dispatches to
        :meth:`_generate_statements_for_type`. Adding a new object type
        is one entry in ``_OBJECT_TYPE_SPECS`` plus the corresponding
        ``expected_*`` field on :class:`DiffGenerationContext` — no
        change to this orchestration code.
        """
        expected_maps = self._build_expected_maps(context)
        statements: List[SqlStatement] = []
        for spec in _OBJECT_TYPE_SPECS:
            statements.extend(
                self._generate_statements_for_type(
                    spec,
                    diff,
                    expected_maps.get(spec.expected_attr, {}),
                    options,
                )
            )
        return statements

    @staticmethod
    def _build_expected_maps(context: DiffGenerationContext) -> Dict[str, Dict[str, Any]]:
        """Materialise the per-object-type expected maps from the context.

        Iterates :data:`_OBJECT_TYPE_SPECS` directly so the key set is
        always in sync with the spec list — adding a new entry to
        ``_OBJECT_TYPE_SPECS`` automatically participates in this map
        with no second list to keep aligned (Bugbot review on PR #352).
        Missing context attributes resolve to an empty dict so the
        downstream loop can index uniformly.
        """
        return {
            spec.expected_attr: getattr(context, f"expected_{spec.expected_attr}", None) or {}
            for spec in _OBJECT_TYPE_SPECS
        }

    # ── Table orchestration methods ───────────────────────────────────

    def _generate_table_changes(
        self,
        table_diff: TableDiff,
        expected_tables: Optional[Dict[str, Table]],
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Generate SQL for table changes."""
        statements: List[SqlStatement] = []

        for column_diff in table_diff.modified_columns:
            column_statements = self.column_converter.convert(
                column_diff, table_diff.table_name, options
            )
            statements.extend(column_statements)

        if expected_tables and table_diff.table_name in expected_tables:
            expected_table = expected_tables[table_diff.table_name]

            add_columns = []
            for column_name in table_diff.missing_columns:
                column = expected_table.get_column(column_name)
                if column:
                    add_columns.append(column)
                else:
                    self.logger.warning(
                        f"Column {column_name} not found in expected "
                        f"table {table_diff.table_name}"
                    )

            add_constraints = []
            for constraint_name in table_diff.missing_constraints:
                constraint = self._find_constraint(expected_table, constraint_name)
                if constraint:
                    add_constraints.append(constraint)
                else:
                    self.logger.warning(
                        f"Constraint {constraint_name} not found in "
                        f"expected table {table_diff.table_name}"
                    )

            drop_constraints = list(table_diff.extra_constraints)

            for constraint_diff in table_diff.modified_constraints:
                drop_constraints.append(constraint_diff.constraint_name)
                constraint = self._find_constraint(expected_table, constraint_diff.constraint_name)
                if constraint:
                    add_constraints.append(constraint)

            alter_statements = self.alter_generator.generate_alter_table_statements(
                table=expected_table,
                add_columns=add_columns if add_columns else None,
                drop_columns=(table_diff.extra_columns if table_diff.extra_columns else None),
                add_constraints=(add_constraints if add_constraints else None),
                drop_constraints=(drop_constraints if drop_constraints else None),
            )

            for sql in alter_statements:
                statements.append(
                    SqlStatement(
                        sql=sql + ";",
                        statement_type="ALTER",
                        object_type="TABLE",
                        object_name=table_diff.table_name,
                        dialect=self.dialect,
                    )
                )

            for index_name in table_diff.missing_indexes:
                index = self._find_table_index(expected_table, index_name)
                if index:
                    create_stmt = self.builder.build_create_sql(
                        _OBJECT_TYPE_SPECS_BY_TYPE["INDEX"], index, options
                    )
                    if create_stmt:
                        statements.append(create_stmt)
                else:
                    self.logger.warning(
                        f"Table-level index {index_name} not found "
                        f"in expected table {table_diff.table_name}"
                    )

            for index_name in table_diff.extra_indexes:
                drop_stmt = self.builder.build_drop_index_sql(
                    index_name, table_diff.table_name, options
                )
                if drop_stmt:
                    statements.append(drop_stmt)

            property_statements = self._generate_table_property_changes(
                table_diff, expected_table, options
            )
            statements.extend(property_statements)
        else:
            for column_name in table_diff.missing_columns:
                self.logger.warning(
                    f"ADD COLUMN for {table_diff.table_name}.{column_name}"
                    f" skipped - expected table definition not provided"
                )

        return statements

    def _find_constraint(self, table: Table, constraint_name: str):
        """Find a constraint by name in a table."""
        for constraint in table.constraints:
            if constraint.name and constraint.name.lower() == constraint_name.lower():
                return constraint
        return None

    def _find_table_index(self, table: Table, index_name: str) -> Optional[Index]:
        """Find an index by name in a table's indexes."""
        if hasattr(table, "indexes"):
            for index in table.indexes:
                if index.name and index.name.lower() == index_name.lower():
                    return index  # type: ignore[return-value,no-any-return]
        return None

    # Properties whose change requires CREATE TABLE ... AS SELECT (no in-place
    # ALTER). Each entry pairs a TableDiff predicate with the human-readable
    # label that ends up in the warning comment. Lifted out of the orchestrator
    # so the diff → label mapping reads as data.
    _RECREATION_REQUIRED_PROPERTIES: Tuple[Tuple[Callable[["TableDiff"], bool], str], ...] = (
        (lambda d: bool(d.temporary_changed), "temporary property"),
        (lambda d: bool(d.filegroup_changed), "filegroup"),
        (lambda d: bool(d.memory_optimized_changed), "memory-optimized property"),
        (lambda d: bool(d.history_table_changed), "history table"),
        (
            lambda d: bool(d.partition_method_changed) or bool(d.partition_columns_changed),
            "partitioning",
        ),
        (
            lambda d: bool(d.compress_changed) or bool(d.compress_type_changed),
            "compression",
        ),
        (lambda d: bool(d.logged_changed), "logged property"),
        (lambda d: bool(d.organize_by_changed), "organize_by property"),
    )

    def _generate_table_property_changes(
        self,
        table_diff: TableDiff,
        expected_table: Table,
        options: GenerationOptions,
    ) -> List[SqlStatement]:
        """Generate SQL for table property changes.

        Three independent phases — kept in the order the original monolith
        emitted them so any downstream ordering assumption is preserved:

        1. Inheritance (PostgreSQL INHERIT / NO INHERIT for changed parents).
        2. System-versioning (SQL Server temporal tables: SET SYSTEM_VERSIONING
           ON/OFF, plus the PERIOD FOR SYSTEM_TIME setup on the ON branch).
        3. Recreation-required warning (collects every changed property that
           can't be ALTERed in place and emits a single advisory comment).
        """
        schema, name = self.builder.parse_table_name(table_diff.table_name)
        formatted_table = self.builder.format_identifier(schema, name)

        statements: List[SqlStatement] = []
        statements.extend(self._emit_inheritance_changes(table_diff, formatted_table))
        statements.extend(
            self._emit_system_versioning_changes(table_diff, expected_table, formatted_table)
        )
        recreation_warning = self._emit_recreation_required_warning(table_diff)
        if recreation_warning is not None:
            statements.append(recreation_warning)
        return statements

    def _emit_inheritance_changes(
        self, table_diff: TableDiff, formatted_table: str
    ) -> List[SqlStatement]:
        """Emit ALTER TABLE INHERIT / NO INHERIT for added/removed parent tables.

        ``table_diff.inherits_changed`` is a ``(expected, actual)`` pair where
        either side can be a scalar table name, a list of names, or falsy.
        Normalised to lists before the set-difference so callers stay simple.
        """
        if table_diff.inherits_changed is None:
            return []

        expected_inherits, actual_inherits = table_diff.inherits_changed
        expected_list = self._coerce_inherits_to_list(expected_inherits)
        actual_list = self._coerce_inherits_to_list(actual_inherits)

        to_add = [t for t in expected_list if t not in actual_list]
        to_remove = [t for t in actual_list if t not in expected_list]

        statements: List[SqlStatement] = []
        for parent_table in to_add:
            parent_formatted = self.builder.format_identifier(None, parent_table)
            statements.append(
                self._alter_table_stmt(
                    table_diff.table_name,
                    f"ALTER TABLE {formatted_table} INHERIT {parent_formatted};",
                )
            )
        for parent_table in to_remove:
            parent_formatted = self.builder.format_identifier(None, parent_table)
            statements.append(
                self._alter_table_stmt(
                    table_diff.table_name,
                    f"ALTER TABLE {formatted_table} NO INHERIT {parent_formatted};",
                )
            )
        return statements

    @staticmethod
    def _coerce_inherits_to_list(value: Any) -> List[str]:
        """Coerce a TableDiff inherits side to a plain list of parent names."""
        if isinstance(value, list):
            return value
        if value:
            return [value]
        return []

    def _emit_system_versioning_changes(
        self, table_diff: TableDiff, expected_table: Table, formatted_table: str
    ) -> List[SqlStatement]:
        """Emit ALTER TABLE statements for SQL Server temporal SYSTEM_VERSIONING.

        Two branches:
        - Turning ON: emits an ADD PERIOD FOR SYSTEM_TIME statement followed by
          SET (SYSTEM_VERSIONING = ON (HISTORY_TABLE = ...)). Defaults for the
          history table name, schema, and period columns come from the
          expected ``Table`` when absent.
        - Turning OFF: a single SET (SYSTEM_VERSIONING = OFF).
        """
        if not table_diff.system_versioned_changed:
            return []

        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect)

        if expected_table.system_versioned:
            history_table = expected_table.history_table or f"{expected_table.name}_History"
            history_schema = expected_table.history_schema or expected_table.schema
            history_formatted = self.builder.format_identifier(history_schema, history_table)
            period_start = expected_table.period_start_column or "SysStartTime"
            period_end = expected_table.period_end_column or "SysEndTime"
            sql = quirks.render_system_versioning_alter(
                formatted_table,
                enable=True,
                history_formatted=history_formatted,
                formatted_period_start=self.builder.quote_identifier(period_start),
                formatted_period_end=self.builder.quote_identifier(period_end),
            )
        else:
            sql = quirks.render_system_versioning_alter(formatted_table, enable=False)

        if not sql:
            return []
        return [self._alter_table_stmt(table_diff.table_name, sql)]

    def _emit_recreation_required_warning(self, table_diff: TableDiff) -> Optional[SqlStatement]:
        """Emit a single advisory COMMENT enumerating every changed property
        that can't be expressed via ALTER TABLE. Returns ``None`` when no
        recreation-required property changed."""
        properties = [
            label
            for predicate, label in self._RECREATION_REQUIRED_PROPERTIES
            if predicate(table_diff)
        ]
        if not properties:
            return None

        props_str = ", ".join(properties)
        warning_sql = (
            f"-- WARNING: Table {table_diff.table_name} requires "
            f"recreation to change {props_str}.\n"
            f"-- This cannot be done with ALTER TABLE. "
            f"Consider using CREATE TABLE ... AS SELECT "
            f"or table migration."
        )
        return SqlStatement(
            sql=warning_sql,
            statement_type="COMMENT",
            object_type="TABLE",
            object_name=table_diff.table_name,
            dialect=self.dialect,
        )

    def _alter_table_stmt(self, table_name: str, sql: str) -> SqlStatement:
        """Build a TableDiff-aware ALTER TABLE SqlStatement with the boilerplate
        kwargs the property-change helpers all share."""
        return SqlStatement(
            sql=sql,
            statement_type="ALTER",
            object_type="TABLE",
            object_name=table_name,
            dialect=self.dialect,
        )
