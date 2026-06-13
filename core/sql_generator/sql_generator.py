"""SQL Generator - Main orchestrator for generating SQL from SQL Model objects.

This module provides the main SqlGenerator class that coordinates SQL generation
from SQL Model objects, handles dependency ordering, and organizes output.
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

from core.sql_generator.formatter import SqlFormatter
from core.sql_generator.options import ScriptOptions
from core.sql_generator.script_organizer import ScriptOrganizer
from core.sql_model.base import SqlObject, SqlObjectType, get_object_type_name

if TYPE_CHECKING:
    from db.base_quirks import BaseQuirks

logger = logging.getLogger(__name__)


def _quirks_for(dialect: Optional[str]) -> "BaseQuirks":
    """Resolve a :class:`BaseQuirks` instance for a dialect string.

    Story 26-3: lets the generator delegate dialect-specific rendering
    to ``provider.quirks`` without ever branching on the dialect name.
    Lazy import keeps ``core.sql_generator`` independent of ``db.*``
    at module load.
    """
    from db.provider_registry import ProviderRegistry

    return ProviderRegistry.get_quirks((dialect or "").lower())


class SqlGenerator:
    """Main orchestrator for generating SQL DDL scripts from SQL Model objects.

    This class coordinates SQL generation using existing `create_statement`
    methods from SQL Model classes, applies formatting, handles dependency
    ordering, and organizes output into files.

    Examples:
        >>> from core.sql_model import Table, Column
        >>> from core.sql_generator import SqlGenerator, ScriptOptions
        >>>
        >>> # Create a table
        >>> table = Table(
        ...     name="users",
        ...     columns=[Column("id", "INTEGER"), Column("name", "VARCHAR(100)")]
        ... )
        >>>
        >>> # Generate SQL
        >>> generator = SqlGenerator()
        >>> sql = generator.generate_ddl([table], target_dialect="postgresql")
        >>> print(sql)
        CREATE TABLE users (
          id INTEGER,
          name VARCHAR(100)
        )
    """

    def __init__(
        self,
        formatter: Optional[SqlFormatter] = None,
        default_dialect: str = "postgresql",  # lint: allow-dialect-string: dialect dispatch
        use_dependency_ordering: bool = True,
    ):
        """Initialize SQL generator.

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
        """Generate DDL statements for a list of objects.

        Uses existing `create_statement` methods from SQL Model classes
        and applies formatting if enabled. Optionally orders by dependencies.

        Args:
            objects: List of SQL Model objects (Table, View, Index, etc.)
            target_dialect: SQL dialect for generation (uses object's dialect if not specified)
            include_comments: Whether to include comments (future: add header comments)
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

        quirks = _quirks_for(dialect)
        for obj in objects:
            try:
                # Dialects that manage indexes outside SQL DDL emit a
                # comment instead of a CREATE INDEX. The comment text
                # is owned by the plugin so the framework never names
                # a specific dialect.
                if quirks.skip_index_ddl():
                    if get_object_type_name(obj) == "INDEX":
                        statements.append(quirks.skip_index_ddl_comment())
                        continue

                # Use existing create_statement method from SQL Model classes
                if not hasattr(obj, "create_statement"):
                    logger.warning(
                        f"Object {obj.name} (type {obj.object_type}) does not have create_statement"
                    )
                    continue
                raw_definition = getattr(obj, "definition", None)
                preserve_definition = self._should_preserve_definition(raw_definition)
                create_sql = raw_definition if preserve_definition else obj.create_statement

                if create_sql:
                    should_format = format_sql and not preserve_definition
                    if should_format and self._should_skip_formatting(obj, create_sql):
                        should_format = False

                    if should_format:
                        create_sql = self.formatter.format(create_sql)

                    create_sql = self._ensure_statement_terminated(create_sql)
                    # Story 26-9 / PR #241 Bugbot: route through the
                    # overridable instance methods so subclasses
                    # (per-dialect generators) can hook in. Both
                    # methods delegate to the plugin's quirks under
                    # the hood, so call sites are still branch-free.
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
                        f"Object {obj.name} (type {obj.object_type}) does not have create_statement"
                    )

            except Exception as e:
                logger.warning(f"Failed to generate DDL for {obj.name}: {e}")
                # Continue with other objects

        # Use dialect-specific formatting
        return self._format_statements(statements, dialect)

    def _requires_dialect_specific_wrapping(self, obj: SqlObject, dialect: str) -> bool:
        """Check if object requires dialect-specific wrapping (e.g., MySQL DELIMITER)."""
        return _quirks_for(dialect).requires_dialect_specific_wrapping(get_object_type_name(obj))

    def _wrap_dialect_specific_block(self, sql: str, dialect: str) -> str:
        """Wrap SQL with dialect-specific delimiters."""
        return _quirks_for(dialect).wrap_dialect_specific_block(sql)

    def _generate_additional_statements(self, obj: SqlObject, dialect: str) -> List[str]:
        """Generate additional statements for an object (e.g., grants, comments)."""
        # For now, return empty list - can be extended later
        return []

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """Format and join statements with appropriate separators."""
        if not statements:
            return ""

        # Join statements with double newlines for readability
        return "\n\n".join(statements)

    @staticmethod
    def _should_preserve_definition(definition: Optional[str]) -> bool:
        """Return True if the provided definition looks like a complete DDL statement."""
        if not isinstance(definition, str):
            return False
        stripped = definition.strip()
        if not stripped:
            return False
        upper = stripped.upper()
        return upper.startswith(("CREATE", "ALTER", "REPLACE"))

    def generate_drop_statements(
        self,
        objects: List[SqlObject],
        target_dialect: Optional[str] = None,
        format_sql: bool = True,
        reverse_order: bool = True,
        order_by_dependencies: Optional[bool] = None,
    ) -> str:
        """Generate DROP statements in reverse dependency order.

        Args:
            objects: List of SQL Model objects to drop
            target_dialect: SQL dialect for generation
            format_sql: Whether to apply SQL formatting
            reverse_order: If True, reverse order for dependencies (views before tables)
            order_by_dependencies: Whether to order by dependencies (default: use instance setting)

        Returns:
            SQL string with all DROP statements
        """
        if not objects:
            return ""

        dialect = target_dialect or self.default_dialect

        if order_by_dependencies is None:
            order_by_dependencies = self.use_dependency_ordering

        statements = []

        # Order objects for DROP (dependents first)
        if order_by_dependencies and len(objects) > 1:
            try:
                sorted_objects = self.script_organizer.get_drop_order(objects)
                # If dependency analysis returned same order or no dependencies detected, use type-based
                # Check if order changed (using names since objects might not be directly comparable)
                if [o.name for o in sorted_objects] == [o.name for o in objects]:
                    sorted_objects = self._sort_by_type_priority(objects, reverse_order)
            except Exception as e:
                logger.warning(f"Dependency ordering for DROP failed: {e}, using type-based order")
                sorted_objects = self._sort_by_type_priority(objects, reverse_order)
        else:
            sorted_objects = self._sort_by_type_priority(objects, reverse_order)

        for obj in sorted_objects:
            try:
                # Try to use drop_statement property if available
                if hasattr(obj, "drop_statement"):
                    drop_sql = obj.drop_statement
                else:
                    # Fallback to helper method
                    drop_sql = self._generate_drop_statement(obj, dialect)

                if drop_sql:
                    if format_sql:
                        drop_sql = self.formatter.format(drop_sql)
                    drop_sql = self._ensure_statement_terminated(drop_sql)
                    statements.append(drop_sql)

            except Exception as e:
                logger.warning(f"Failed to generate DROP for {obj.name}: {e}")

        return "\n\n".join(stmt for stmt in statements if stmt.strip())

    def _ensure_statement_terminated(self, sql: str) -> str:
        """Ensure SQL statement ends with a terminator."""
        if not sql:
            return sql

        stripped = sql.rstrip()
        if not stripped:
            return stripped

        terminators = (";", "/", "$$")
        if stripped.endswith(terminators):
            return stripped

        return f"{stripped};"

    @staticmethod
    def _should_skip_formatting(obj: SqlObject, sql: str) -> bool:
        """Return True if the formatter should be bypassed for this object."""
        if not sql:
            return False

        if obj.object_type == SqlObjectType.TABLE and getattr(obj, "partition_method", None):
            # sqlglot's formatter is unaware of CREATE TABLE PARTITION BY clauses
            return True

        if obj.object_type == SqlObjectType.PACKAGE:
            # Preserve CREATE PACKAGE formatting (requires trailing '/' separators)
            return True

        dialect = getattr(obj, "dialect", None)
        if dialect and _quirks_for(dialect).preserves_object_definition(get_object_type_name(obj)):
            # Preserve verbatim definition (e.g. MySQL DEFINER clauses).
            return True

        return False

    def _sort_by_type_priority(
        self, objects: List[SqlObject], reverse: bool = True
    ) -> List[SqlObject]:
        """Sort objects by type priority (fallback when dependency analysis unavailable).

        Args:
            objects: Objects to sort
            reverse: If True, reverse order

        Returns:
            Sorted objects
        """
        type_priority = {
            "TRIGGER": 1,
            "VIEW": 2,
            "MATERIALIZED_VIEW": 2,
            "INDEX": 3,
            "SEQUENCE": 3,
            "TABLE": 4,
            "PROCEDURE": 5,
            "FUNCTION": 5,
        }

        # For DROP (reverse=True), we want dependents first (VIEW before TABLE)
        # VIEW has priority 2, TABLE has priority 4
        # We want ascending order (2 < 4), so VIEW comes before TABLE
        # This means reverse=False when sorting by priority for DROP
        # For CREATE (reverse=False), we want dependencies first (TABLE before VIEW)
        # This means descending order (4 > 2), so TABLE comes before VIEW
        # This means reverse=True when sorting by priority for CREATE
        return sorted(
            objects,
            key=lambda obj: type_priority.get(
                get_object_type_name(obj),
                99,
            ),
            reverse=not reverse,  # Invert: DROP needs ascending, CREATE needs descending
        )

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """Generate a DROP statement for an object.

        This is a temporary implementation until drop_statement() methods
        are added to SQL Model classes.

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect

        Returns:
            DROP statement SQL string
        """
        schema_prefix = ""
        if obj.schema:
            schema_prefix = f"{obj.format_identifier(obj.schema)}."

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)
        table_name = getattr(obj, "table_name", None)

        # Story 26-3: dialect-specific drop variants live on the
        # plugin's quirks. The framework asks first; only when the
        # plugin returns ``None`` does it fall back to the generic
        # form below. ``sql_generator.py`` no longer names a dialect.
        custom = _quirks_for(dialect).render_drop_for_object(
            obj_type, obj_name, schema_prefix, table_name
        )
        if custom is not None:
            return custom

        # Generic fallback: build ``DROP <type> [IF EXISTS] <name> [CASCADE]``
        # using ``Quirks`` flags. Avoid emitting ``IF EXISTS`` and
        # ``CASCADE`` blindly — Oracle has no ``IF EXISTS``, MySQL/SQL
        # Server reject ``CASCADE`` on ``DROP TABLE``, etc. Plugins
        # expressing dialect-specific shapes via
        # ``render_drop_for_object`` short-circuit before this fallback.
        # (PR #241 Bugbot.)
        quirks = _quirks_for(dialect)
        if_exists = "IF EXISTS " if quirks.drop_supports_if_exists else ""
        cascade = " CASCADE" if obj_type == "TABLE" and quirks.drop_table_default_cascade else ""
        return f"DROP {obj_type} {if_exists}{schema_prefix}{obj_name}{cascade}"

    def generate_schema_script(
        self,
        schema: Dict[str, List[SqlObject]],
        target_dialect: Optional[str] = None,
        options: Optional[ScriptOptions] = None,
    ) -> Dict[str, str]:
        """Generate complete schema script with organization.

        Takes a schema dictionary (from SchemaIntrospector) and generates
        organized SQL scripts based on options with dependency ordering.

        Args:
            schema: Dictionary mapping object types to lists of objects
                   (e.g., {"tables": [Table, ...], "views": [View, ...]})
            target_dialect: SQL dialect for generation
            options: Script generation options

        Returns:
            Dictionary mapping file names to SQL content
        """
        if options is None:
            options = ScriptOptions()

        dialect = target_dialect or self.default_dialect

        # Collect all objects
        all_objects = []
        for obj_list in schema.values():
            if isinstance(obj_list, list):
                all_objects.extend(obj_list)

        # Use script organizer for dependency-aware organization
        organized_files = self.script_organizer.organize(all_objects, options)

        # Generate SQL content for each file
        files = {}
        for file_name, file_objects in organized_files.items():
            # Generate CREATE statements
            create_sql = self.generate_ddl(
                file_objects,
                target_dialect=dialect,
                include_comments=options.include_comments,
                format_sql=options.format_sql,
                order_by_dependencies=True,
            )

            # Add DROP statements if requested
            if options.include_drops:
                drop_sql = self.generate_drop_statements(
                    file_objects,
                    target_dialect=dialect,
                    format_sql=options.format_sql,
                    order_by_dependencies=True,
                )
                sql_content = f"{drop_sql}\n\n{create_sql}"
            else:
                sql_content = create_sql

            # Add header comments if enabled
            if options.include_comments:
                header = self.script_organizer.generate_file_header(
                    file_name, len(file_objects), dialect
                )
                footer = self.script_organizer.generate_file_footer(file_name)
                sql_content = f"{header}{sql_content}\n{footer}"

            files[file_name] = sql_content

        return files
