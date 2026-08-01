"""
Base class for database-specific SQL generation.

This module provides the abstract base class that all database-specific
SQL generators must implement. It defines the common interface and shared
functionality for SQL generation.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional

if TYPE_CHECKING:
    from core.sql_model.procedure import Procedure
    from core.sql_model.view import View

from core.sql_generator.formatter import SqlFormatter
from core.sql_generator.options import ScriptOptions
from core.sql_generator.script_organizer import ScriptOrganizer
from core.sql_model.base import SqlObject, SqlObjectType, get_object_type_name

logger = logging.getLogger(__name__)


def _schema_prefix_from_object(obj) -> str:
    """Return 'schema.' or '' — combines format_identifier + _build_schema_prefix.

    Single canonical implementation shared by BaseSqlGenerator (via @staticmethod
    delegation) and BasicTableDdlGenerator (via direct import).

    Args:
        obj: Any SqlObject with .schema and .format_identifier() attributes

    Returns:
        Schema prefix string with trailing dot, or empty string if no schema
    """
    if not obj.schema:
        return ""
    return f"{obj.format_identifier(obj.schema)}."


class BaseSqlGenerator(ABC):
    """
    Abstract base class for database-specific SQL generation.

    Each database type (PostgreSQL, Oracle, MySQL, etc.) should implement
    this interface to provide database-specific SQL generation logic while
    sharing common functionality.

    Example:
        >>> generator = PostgreSQLSqlGenerator(default_dialect="postgresql")
        >>> sql = generator.generate_ddl([table])
    """

    _SYSTEM_FUNCTION_NAMES: frozenset[str] = frozenset(
        {
            "<",
            "<=",
            "<>",
            "=",
            ">",
            ">=",
            "VARCHAR",
            "INTEGER",
            "DECIMAL",
            "TIMESTAMP",
        }
    )

    @staticmethod
    def _is_system_function(procedure: "Procedure") -> bool:
        """Return True if procedure should be skipped as a system function.

        Detects system functions/operators by:
        - Name membership in _SYSTEM_FUNCTION_NAMES (operators, SQL types)
        - OID-based return_type (int), indicating an internal PostgreSQL OID reference

        Note: Uses BaseSqlGenerator._SYSTEM_FUNCTION_NAMES explicitly (not cls),
        as @staticmethod has no class reference. Subclasses that need a different
        set should override _is_system_function() directly.

        Args:
            procedure: The Procedure object to check.

        Returns:
            True if this is a system function that should not generate SQL.
        """
        return procedure.name in BaseSqlGenerator._SYSTEM_FUNCTION_NAMES or (
            bool(procedure.return_type) and isinstance(procedure.return_type, int)
        )

    def __init__(
        self,
        formatter: Optional[SqlFormatter] = None,
        default_dialect: str = "",
        use_dependency_ordering: bool = True,
    ):
        """
        Initialize the base SQL generator.

        Args:
            formatter: Optional SQL formatter instance. If None, creates one
                     with default_dialect
            default_dialect: Default SQL dialect for formatting
            use_dependency_ordering: Whether to order objects by dependencies
        """
        self.formatter = formatter or SqlFormatter(dialect=default_dialect)
        self.default_dialect = default_dialect
        self.script_organizer = ScriptOrganizer()
        self.use_dependency_ordering = use_dependency_ordering

    def generate_ddl(
        self,
        objects: List[SqlObject],
        target_dialect: Optional[str] = None,
        include_comments: bool = True,
        format_sql: bool = True,
        order_by_dependencies: Optional[bool] = None,
    ) -> str:
        """
        Generate DDL statements for a list of objects.

        Uses existing `create_statement` methods from SQL Model classes
        and applies formatting if enabled. Optionally orders by dependencies.

        Args:
            objects: List of SQL Model objects (Table, View, Index, etc.)
            target_dialect: SQL dialect for generation (uses object's dialect if not specified)
            include_comments: Whether to include comments
            format_sql: Whether to apply SQL formatting
            order_by_dependencies: Whether to order by dependencies (default: use instance setting)

        Returns:
            SQL string with all CREATE statements
        """
        if not objects:
            return ""

        dialect = target_dialect or self.default_dialect

        # Update formatter dialect if needed
        if target_dialect and target_dialect != self.formatter.dialect:
            self.formatter = SqlFormatter(dialect=target_dialect)

        # Order by dependencies if requested
        if order_by_dependencies is None:
            order_by_dependencies = self.use_dependency_ordering

        if order_by_dependencies and len(objects) > 1:
            try:
                ordered_objects = self.script_organizer.dependency_analyzer.get_create_order(
                    objects
                )
                objects = ordered_objects
            except Exception as e:
                logger.warning(f"Dependency ordering failed: {e}, using original order")

        statements = []

        for obj in objects:
            try:
                # Use database-specific create statement generation
                raw_definition = getattr(obj, "definition", None)
                preserve_definition = self._should_preserve_object_definition(obj, raw_definition)

                if preserve_definition:
                    create_sql = raw_definition
                else:
                    # Use the database-specific generator instead of obj.create_statement
                    create_sql = self.generate_create_statement(obj)

                if create_sql:
                    should_format = format_sql and not preserve_definition
                    if should_format and self._should_skip_formatting(obj, create_sql):
                        should_format = False

                    if should_format:
                        create_sql = self.formatter.format(create_sql)

                    create_sql = self._postprocess_create_statement(obj, create_sql, dialect)
                    create_sql = self._ensure_statement_terminated(create_sql)
                    if self._requires_dialect_specific_wrapping(obj, dialect):
                        create_sql = self._wrap_dialect_specific_block(create_sql, dialect)
                    statements.append(create_sql)

                    # Dialect-specific post-processing
                    additional_statements = self._generate_additional_statements(obj, dialect)
                    for stmt in additional_statements:
                        stmt = self._ensure_statement_terminated(stmt)
                        statements.append(stmt)
                else:
                    logger.warning(
                        f"Object {obj.name} (type {obj.object_type}) generated empty CREATE statement"
                    )
            except Exception as e:
                logger.warning(f"Error generating DDL for {obj.name}: {e}")

        # Use dialect-specific formatting
        return self._format_statements(statements, dialect)

    @abstractmethod
    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (dialect-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect

        Returns:
            DROP statement SQL string
        """

    def generate_create_statement(self, obj: SqlObject) -> str:
        """
        Generate a CREATE statement for an SQL object using the type dispatch registry.

        Args:
            obj: SQL Model object to generate CREATE statement for

        Returns:
            CREATE statement SQL string
        """
        for obj_type, method_name in self._get_create_dispatch().items():
            if isinstance(obj, obj_type):
                return str(getattr(self, method_name)(obj))
        return self._generate_create_fallback(obj)

    #: Central registry mapping SQL object type → handler method name.
    #: Populated lazily on first call to _get_create_dispatch() to avoid
    #: circular imports at class-definition time.  Subclasses extend this
    #: by calling super()._get_create_dispatch() and updating with
    #: dialect-specific entries.
    _CREATE_DISPATCH: ClassVar[Dict[type, str]] = {}

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: handler method name} for the 8 common types.

        Loads the common SQL object types shared by all 5 dialect generators
        (View, Index, Procedure, Table, Synonym, Sequence, UserDefinedType,
        Trigger).  Imports are deferred to avoid circular imports at
        class-definition time.

        Subclasses should call ``super()._get_create_dispatch()`` and update
        with any dialect-specific entries, e.g.::

            def _get_create_dispatch(self) -> dict[type, str]:
                dispatch = super()._get_create_dispatch()
                from core.sql_model.package import Package
                dispatch[Package] = "_generate_package_create_statement"
                return dispatch
        """
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        return {
            View: "_generate_view_create_statement",
            Index: "_generate_index_create_statement",
            Procedure: "_generate_procedure_create_statement",
            Table: "_generate_table_create_statement",
            Synonym: "_generate_synonym_create_statement",
            Sequence: "_generate_sequence_create_statement",
            UserDefinedType: "_generate_user_defined_type_create_statement",
            Trigger: "_generate_trigger_create_statement",
        }

    def _generate_create_fallback(self, obj: SqlObject) -> str:
        """Called when no type matches in dispatch. Override in subclasses."""
        return getattr(obj, "create_statement", "")

    def generate_drop_statements(
        self,
        objects: List[SqlObject],
        target_dialect: Optional[str] = None,
        format_sql: bool = True,
        order_by_dependencies: Optional[bool] = None,
    ) -> str:
        """
        Generate DROP statements for a list of objects.

        Args:
            objects: List of SQL Model objects to drop
            target_dialect: SQL dialect for generation
            format_sql: Whether to apply SQL formatting
            order_by_dependencies: Whether to order by dependencies (default: use instance setting)

        Returns:
            SQL string with all DROP statements
        """
        if not objects:
            return ""

        dialect = target_dialect or self.default_dialect

        # Order by dependencies (reverse order for DROP)
        if order_by_dependencies is None:
            order_by_dependencies = self.use_dependency_ordering

        if order_by_dependencies and len(objects) > 1:
            try:
                ordered_objects = self.script_organizer.dependency_analyzer.get_drop_order(objects)
                objects = ordered_objects
            except Exception as e:
                logger.warning(f"Dependency ordering failed: {e}, using original order")

        statements = []

        for obj in objects:
            try:
                drop_sql = self._generate_drop_statement(obj, dialect)
                if drop_sql:
                    if format_sql:
                        drop_sql = self.formatter.format(drop_sql)
                    drop_sql = self._ensure_statement_terminated(drop_sql)
                    statements.append(drop_sql)
            except Exception as e:
                logger.warning(f"Error generating DROP for {obj.name}: {e}")

        # Use dialect-specific formatting
        return self._format_statements(statements, dialect)

    def generate_schema_script(
        self,
        schema: Dict[str, List[SqlObject]],
        target_dialect: Optional[str] = None,
        options: Optional[ScriptOptions] = None,
    ) -> Dict[str, str]:
        """
        Generate complete schema script with organization.

        Takes a schema dictionary (from SchemaIntrospector) and generates
        organized SQL scripts based on options with dependency ordering.

        Args:
            schema: Dictionary mapping object types to lists of objects
            target_dialect: SQL dialect for generation
            options: Script organization options

        Returns:
            Dictionary mapping file names to SQL content
        """
        if options is None:
            options = ScriptOptions()

        dialect = target_dialect or self.default_dialect

        # Flatten schema dictionary into a single list
        all_objects: List[SqlObject] = []
        for object_list in schema.values():
            all_objects.extend(object_list)

        # Organize objects into files first
        organized_files = self.script_organizer.organize(all_objects, options)

        # Generate SQL for each organized file
        result: Dict[str, str] = {}
        for filename, objects in organized_files.items():
            # Generate CREATE statements
            create_sql = self.generate_ddl(
                objects,
                target_dialect=dialect,
                include_comments=options.include_comments,
                format_sql=options.format_sql,
                order_by_dependencies=True,
            )

            # Generate DROP statements if requested
            drop_sql = ""
            if options.include_drops:
                drop_sql = self.generate_drop_statements(
                    objects,
                    target_dialect=dialect,
                    format_sql=options.format_sql,
                    order_by_dependencies=True,
                )

            # Combine CREATE and DROP SQL
            file_content = ""
            if drop_sql:
                file_content += f"-- DROP statements\n{drop_sql}\n\n"
            if create_sql:
                file_content += f"-- CREATE statements\n{create_sql}"

            result[filename] = file_content

        return result

    # Helper methods with default implementations

    def _should_preserve_definition(self, definition: Optional[str]) -> bool:
        """Check if we should preserve the raw definition."""
        if not definition:
            return False
        stripped = definition.strip().upper()
        return stripped.startswith(("CREATE", "ALTER", "REPLACE"))

    def _should_preserve_object_definition(self, obj: SqlObject, definition: Optional[str]) -> bool:
        return self._should_preserve_definition(definition)

    def _postprocess_create_statement(self, obj: SqlObject, create_sql: str, dialect: str) -> str:
        return create_sql

    def _should_skip_formatting(self, obj: SqlObject, sql: str) -> bool:
        """Check if we should skip formatting for this object."""
        # Skip formatting for objects that need special handling
        if obj.object_type in {
            SqlObjectType.PROCEDURE,
            SqlObjectType.FUNCTION,
            SqlObjectType.TRIGGER,
            SqlObjectType.EVENT,
        }:
            # Preserve MySQL DEFINER clauses and identifier quoting
            return True
        return False

    def _requires_dialect_specific_wrapping(self, obj: SqlObject, dialect: str) -> bool:
        """Check if object needs dialect-specific wrapping.

        Uses the NARROWER ``requires_dialect_specific_wrapping`` hook
        (PROCEDURE/FUNCTION only for MySQL) — matching the contract
        of the default ``_wrap_dialect_specific_block`` (a no-op
        pass-through). Plugin DDL generators that need the wider
        TRIGGER/EVENT set (``MySQLSqlGenerator``) override BOTH this
        predicate and ``_wrap_dialect_specific_block`` so the pair
        stays consistent.

        The TRIGGER/EVENT wrapping for MySQL is also provided by the
        separate ``$$`` path
        (``_requires_mysql_delimiter`` / ``_wrap_mysql_delimiter_block``
        in ``sql_generator.py``), which uses the wider
        ``requires_block_delimiter_wrapping`` quirks hook.

        (PR #241 Bugbot: earlier refactor caused predicate/wrapper
        mismatch where the predicate fired for triggers/events but the
        no-op wrapper didn't actually wrap.)
        """
        if not dialect:
            return False
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.get_quirks(dialect.lower()).requires_dialect_specific_wrapping(
            get_object_type_name(obj)
        )

    def _wrap_dialect_specific_block(self, sql: str, dialect: str) -> str:
        """Default: pass-through (no wrapping).

        Plugin DDL generators (e.g. ``MysqlSqlGenerator``) override
        this with their own wrap string. Historical behaviour, kept
        deliberately: the predicate / wrapper pair in the base class
        was pre-existing no-op; an earlier refactor incorrectly piped
        the no-op into ``quirks.wrap_dialect_specific_block`` (which
        actively wraps with ``DELIMITER //``), creating a double-wrap
        risk against the separate ``$$`` path
        (``_requires_mysql_delimiter`` / ``_wrap_mysql_delimiter_block``
        in ``sql_generator.py``). Reverted to no-op so plugin
        overrides remain authoritative. (PR #241 Bugbot.)
        """
        return sql

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for the dialect (default: newline-separated).

        Override in subclasses for dialect-specific formatting (e.g., SQL Server GO).

        Args:
            statements: List of SQL statements
            dialect: SQL dialect

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _generate_additional_statements(self, obj: SqlObject, dialect: str) -> List[str]:
        """Generate additional statements needed after CREATE (dialect-specific)."""
        additional = []

        # For dialects that require post-CREATE ALTER for CHECK constraints (DB2),
        # generate ALTER TABLE statements via the table object.
        if hasattr(obj, "generate_alter_table_check_constraints") and dialect:
            from db.provider_registry import ProviderRegistry

            if ProviderRegistry.get_quirks(dialect).table_check_via_alter:
                alter_statements = obj.generate_alter_table_check_constraints()
                additional.extend(alter_statements)

        # Generate COMMENT ON INDEX statements for indexes with comments
        if hasattr(obj, "comment") and hasattr(obj, "name") and hasattr(obj, "schema"):
            from core.sql_model.index import Index

            if isinstance(obj, Index) and obj.comment:
                comment_stmt = self._generate_index_comment_statement(obj, dialect)
                if comment_stmt:
                    additional.append(comment_stmt)

        return additional

    @staticmethod
    def _build_schema_prefix(schema_name: Optional[str]) -> str:
        """Return 'schema_name.' or '' if schema_name is falsy.

        Args:
            schema_name: Formatted schema identifier (e.g., '"public"' or 'myschema')

        Returns:
            Schema prefix string with trailing dot, or empty string
        """
        return f"{schema_name}." if schema_name else ""

    @staticmethod
    def _schema_prefix_from_object(obj) -> str:
        """Return 'schema.' or '' — delegates to module-level canonical function.

        Args:
            obj: Any SqlObject with .schema and .format_identifier() attributes

        Returns:
            Schema prefix string with trailing dot, or empty string if no schema
        """
        return _schema_prefix_from_object(obj)

    @staticmethod
    def _build_view_statement_prefix(view: "View") -> str:
        """Return the common '{view_type} {schema.}name' fragment for CREATE VIEW statements.

        Computes schema_prefix, view_name (formatted identifier), and view_type
        (MATERIALIZED VIEW or VIEW) — the three setup lines common to all 5
        dialect-specific _generate_view_create_statement() methods.

        Args:
            view: The View object to build the prefix for.

        Returns:
            Fragment string, e.g. "VIEW myschema.my_view" or
            "MATERIALIZED VIEW myschema.my_mview". Dialect-specific CREATE keyword
            and pre/post clauses are the responsibility of each generator.
        """
        schema_prefix = BaseSqlGenerator._schema_prefix_from_object(view)
        view_name = view.format_identifier(view.name)
        view_type = "MATERIALIZED VIEW" if view.materialized else "VIEW"
        return f"{view_type} {schema_prefix}{view_name}"

    @staticmethod
    def _build_view_columns_clause(view: "View") -> str:
        """Return ' (col1, col2, ...)' column list clause for CREATE VIEW, or ''.

        The returned string includes the leading space when non-empty, so callers
        can unconditionally append it: stmt += self._build_view_columns_clause(view)

        Args:
            view: The View object; view.columns is a list of column name strings.

        Returns:
            ' (formatted_col1, formatted_col2, ...)' or '' if no columns defined.
        """
        if not view.columns:
            return ""
        formatted_columns = [view.format_identifier(col) for col in view.columns]
        return f" ({', '.join(formatted_columns)})"

    def _generate_index_comment_statement(self, index: Any, dialect: str) -> str:  # Index
        """Generate COMMENT ON INDEX statement for index comments.

        Args:
            index: Index object with comment
            dialect: SQL dialect

        Returns:
            COMMENT ON INDEX statement or empty string if not supported
        """
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(index)
        idx_name = index.format_identifier(index.name)

        # Escape single quotes in comment
        escaped_comment = (index.comment or "").replace("'", "''")

        from db.provider_registry import ProviderRegistry

        template = ProviderRegistry.get_quirks(dialect).index_comment_template
        if not template:
            return ""
        return template.format(
            schema_prefix=schema_prefix,
            idx_name=idx_name,
            escaped_comment=escaped_comment,
        )

    def _ensure_statement_terminated(self, sql: str) -> str:
        """Ensure SQL statement ends with semicolon."""
        if not sql:
            return sql
        stripped = sql.rstrip()
        if not stripped.endswith(";"):
            return stripped + ";"
        return stripped
