"""Hybrid SQL parser combining regex-based and sqlglot-based parsing.

This module provides a hybrid parser that leverages the strengths of both approaches:
- Regex parsers: Excellent for procedural language splitting and dialect-specific delimiters
- SqlGlot parser: Superior for pure SQL analysis, dependencies, and basic object extraction

The hybrid approach:
1. Uses regex parsers for statement splitting (handles procedural languages)
2. Uses sqlglot for dependency extraction and basic object identification
3. Falls back gracefully when sqlglot cannot parse (procedural blocks, edge cases)

NOTE: While the diff command now relies on introspection-based models, other subsystems (rule
engine, SQL analyzer, CLI validations) still rely on lightweight SQLModel metadata. This parser
therefore recreates essential table metadata (columns, constraints, partition schemes) directly
from CREATE TABLE statements so that downstream consumers retain the information they need.
"""

import inspect
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlglot import exp, parse_one

from core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlColumn,
    SqlConstraint,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
)
from core.sql_model.database_link import DatabaseLink
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.package import Package
from core.sql_model.partition import Partition
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View
from core.sql_parser._sqlglot_builders import _SqlglotBuildersMixin
from core.sql_parser.parser_interface import SqlParserInterface
from core.sql_parser.sqlglot_parser import SqlGlotParser

logger = logging.getLogger(__name__)


def _resolve_regex_parser(dialect: str) -> "SqlParserInterface":
    """Resolve the regex parser for *dialect* via the plugin's quirks (OCP / DIP)."""
    from db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(dialect)
    cls = quirks.parser_class("regex")
    if cls is None:
        raise ValueError(f"Unsupported dialect: {dialect}")
    return cls()  # type: ignore[no-any-return]


# Dispatch dict for _collect_objects: SqlObjectType → (expected_class, get_collection, add_method_name)
# get_collection=None means no dedup check (e.g., PARTITION)
_COLLECT_DISPATCH: Dict[SqlObjectType, Tuple[type, Optional[Any], str]] = {
    SqlObjectType.TABLE: (Table, lambda r: r.tables, "add_table"),
    SqlObjectType.VIEW: (View, lambda r: r.views, "add_view"),
    SqlObjectType.MATERIALIZED_VIEW: (View, lambda r: r.views, "add_view"),
    SqlObjectType.INDEX: (Index, lambda r: r.indexes, "add_index"),
    SqlObjectType.SEQUENCE: (Sequence, lambda r: r.sequences, "add_sequence"),
    SqlObjectType.TRIGGER: (Trigger, lambda r: r.triggers, "add_trigger"),
    SqlObjectType.PROCEDURE: (Procedure, lambda r: r.procedures, "add_procedure"),
    SqlObjectType.FUNCTION: (Procedure, lambda r: r.functions, "add_function"),
    SqlObjectType.SYNONYM: (Synonym, lambda r: r.synonyms, "add_synonym"),
    SqlObjectType.TYPE: (UserDefinedType, lambda r: r.user_defined_types, "add_user_defined_type"),
    SqlObjectType.PACKAGE: (Package, lambda r: r.packages, "add_package"),
    SqlObjectType.EVENT: (Event, lambda r: r.events, "add_event"),
    SqlObjectType.EXTENSION: (Extension, lambda r: r.extensions, "add_extension"),
    SqlObjectType.FOREIGN_DATA_WRAPPER: (
        ForeignDataWrapper,
        lambda r: r.foreign_data_wrappers,
        "add_foreign_data_wrapper",
    ),
    SqlObjectType.FOREIGN_SERVER: (
        ForeignServer,
        lambda r: r.foreign_servers,
        "add_foreign_server",
    ),
    SqlObjectType.DATABASE_LINK: (DatabaseLink, lambda r: r.database_links, "add_database_link"),
    SqlObjectType.PARTITION: (Partition, None, "add_partition"),
}


class HybridParser(_SqlglotBuildersMixin, SqlParserInterface):
    """Hybrid SQL parser combining regex and sqlglot approaches.

    This parser provides the best of both worlds:
    - Regex parsers handle procedural languages and dialect-specific syntax
    - SqlGlot enhances pure SQL with dependency extraction and basic object identification

    Strategy:
    1. Split statements using regex parser (handles PL/SQL, T-SQL, etc.)
    2. Classify statement type using regex parser
    3. Extract basic objects (name, schema, type) using both parsers
    4. Extract dependencies using sqlglot when available

    Note: Detailed metadata extraction (e.g., full table schemas with columns and constraints)
    has been removed as it's no longer needed for diff comparison.
    """

    # Statement types that are "pure SQL" and can benefit from sqlglot analysis
    PURE_SQL_TYPES = {
        SqlStatementType.SELECT,
        SqlStatementType.INSERT,
        SqlStatementType.UPDATE,
        SqlStatementType.DELETE,
        SqlStatementType.QUERY,
        SqlStatementType.MERGE,
    }

    # Keywords indicating procedural language (not pure SQL)
    PROCEDURAL_KEYWORDS = [
        "CREATE PROCEDURE",
        "CREATE FUNCTION",
        "CREATE TRIGGER",
        "CREATE EVENT",  # MySQL scheduled events
        "CREATE PACKAGE",
        "CREATE OR REPLACE PROCEDURE",
        "CREATE OR REPLACE FUNCTION",
        "CREATE OR REPLACE TRIGGER",
        "CREATE OR REPLACE EVENT",
        "CREATE OR REPLACE PACKAGE",
        "BEGIN",  # PL/SQL blocks
        "DECLARE",  # Variable declarations
    ]

    def __init__(self, dialect: str):
        """Initialize hybrid parser with both regex and sqlglot parsers.

        Args:
            dialect: SQL dialect name (oracle, mysql, postgresql, sqlserver, db2)
        """
        self.dialect = dialect.lower()

        # Initialize regex parser for this dialect
        self.regex_parser = self._get_regex_parser(dialect)

        # Initialize sqlglot parser (only when the plugin declares a sqlglot dialect).
        from db.provider_registry import ProviderRegistry

        self._quirks = ProviderRegistry.get_quirks(self.dialect)
        self.sqlglot_parser = None
        if self._quirks.sqlglot_dialect is not None:
            try:
                self.sqlglot_parser = SqlGlotParser(dialect)
                logger.debug(f"Initialized HybridParser with sqlglot support for {dialect}")
            except Exception as e:
                logger.debug(f"SqlGlot not available for {dialect}: {e}")
                self.sqlglot_parser = None
        else:
            logger.debug(f"Initialized HybridParser with regex-only for {dialect}")

    @property
    def dialect_name(self) -> str:
        """Return the name of the SQL dialect this parser handles."""
        return self.dialect

    def _get_regex_parser(self, dialect: str) -> SqlParserInterface:
        """Resolve the regex parser via the plugin's quirks (OCP / DIP)."""
        return _resolve_regex_parser(dialect.lower())

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content using hybrid approach.

        Uses regex parser for statement splitting and classification,
        then enhances pure SQL statements with sqlglot analysis.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult with enhanced statement information

        Raises:
            TypeError: If sql_content is not a string
        """
        # Validate input type
        if not isinstance(sql_content, str):
            raise TypeError(f"sql_content must be a string, got {type(sql_content).__name__}")

        try:
            result = self.regex_parser.parse_sql(sql_content, default_schema)

            if not result.success:
                return result

            collected_objects = False
            enhanced_statements: List[SqlStatement] = []
            for stmt in result.statements or []:
                enhanced_stmt = self._enhance_statement(stmt, default_schema)
                enhanced_statements.append(enhanced_stmt)

                if enhanced_stmt.objects:
                    collected_objects = True
                    self._collect_objects(result, enhanced_stmt.objects)

                self._ensure_table_metadata(enhanced_stmt, default_schema, result)
                self._ensure_alter_table_metadata(enhanced_stmt, default_schema, result)
                self._ensure_view_metadata(enhanced_stmt, default_schema, result)
                self._ensure_index_metadata(enhanced_stmt, default_schema, result)
                self._ensure_trigger_metadata(enhanced_stmt, default_schema, result)

            if enhanced_statements:
                result.statements = enhanced_statements

            if not collected_objects:
                fallback_objects = self.extract_objects(sql_content, default_schema)
                if fallback_objects:
                    self._collect_objects(result, fallback_objects)

            return result

        except Exception as e:
            error_msg = f"Error in hybrid parsing: {str(e)}"
            logger.error(error_msg)
            return ParseResult(success=False, statements=[], errors=[error_msg])

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into statements using regex parser.

        Regex parsers excel at handling:
        - Procedural language blocks (PL/SQL, T-SQL, etc.)
        - Special delimiters (Oracle /, MySQL DELIMITER, PostgreSQL $$)
        - Complex string literals and quotes

        Args:
            sql_content: SQL content to split
            strict_tokenizer: If True, dialect tokenizers fail on unknown
                characters instead of falling back to permissive splitting.

        Returns:
            List of SQL statement strings
        """
        try:
            split_signature = inspect.signature(self.regex_parser.split_statements)
            supports_strict = "strict_tokenizer" in split_signature.parameters
        except (TypeError, ValueError):
            supports_strict = False
        if supports_strict:
            return self.regex_parser.split_statements(
                sql_content, strict_tokenizer=strict_tokenizer
            )
        return self.regex_parser.split_statements(sql_content)

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL using both parsers.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dict with validation results
        """
        # Start with regex validation
        result = self.regex_parser.validate_sql(sql_content)

        # If sqlglot available and content looks like pure SQL, try sqlglot validation
        if (
            self.sqlglot_parser
            and not self._contains_procedural_keywords(sql_content)
            and not self._is_sqlglot_opaque_valid_ddl(sql_content)
        ):
            try:
                sqlglot_result = self.sqlglot_parser.validate_sql(sql_content)
                # Merge errors from both parsers
                if not sqlglot_result["valid"]:
                    result["errors"].extend(sqlglot_result["errors"])
                    result["valid"] = False
            except Exception as e:
                logger.debug(f"SqlGlot validation failed (expected for procedural): {e}")

        return result

    def _is_sqlglot_opaque_valid_ddl(self, sql_content: str) -> bool:
        """Known-valid dialect DDL that sqlglot may not parse faithfully."""
        return self._quirks.is_sqlglot_opaque_valid_ddl(sql_content)

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects using hybrid approach.

        Args:
            sql_content: SQL content to extract objects from
            default_schema: Default schema name

        Returns:
            List of extracted SQL objects
        """
        # Get objects from regex parser
        regex_objects = self.regex_parser.extract_objects(sql_content, default_schema)

        # If sqlglot available and content is pure SQL, enhance with sqlglot
        # Skip sqlglot for Oracle-specific syntax it doesn't support (e.g. PARTITION BY REFERENCE)
        use_sqlglot = (
            self.sqlglot_parser is not None
            and not self._contains_procedural_keywords(sql_content)
            and not self._contains_oracle_sqlglot_unsupported(sql_content)
        )
        if use_sqlglot and self.sqlglot_parser is not None:
            try:
                sqlglot_objects = self.sqlglot_parser.extract_objects(sql_content, default_schema)
                # Merge objects, preferring sqlglot for duplicates (more accurate)
                return self._merge_objects(regex_objects, sqlglot_objects)
            except Exception as e:
                logger.debug(f"SqlGlot object extraction failed, using regex only: {e}")

        return regex_objects

    def extract_dependencies(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """Extract object dependencies using sqlglot (when available)."""
        deps: Dict[str, List[str]] = {"tables": [], "views": [], "schemas": []}
        if not self.sqlglot_parser:
            logger.debug("SqlGlot not available for dependency extraction")
            return deps

        try:
            for stmt_text in self.split_statements(sql_content):
                if self._should_skip_dependency_statement(stmt_text):
                    continue
                try:
                    ast = parse_one(stmt_text, read=self.sqlglot_parser.sqlglot_dialect)
                except Exception as parse_exc:
                    logger.debug(
                        f"SqlGlot dependency parsing failed, skipping statement: {parse_exc}"
                    )
                    continue
                # ``parse_one`` is typed ``Expr | None`` in newer sqlglot.
                # Skip when the parser returned no AST (or the base ``Expr``
                # alone) so the downstream extractor only sees a concrete
                # ``Expression`` it can introspect.
                if not isinstance(ast, exp.Expression):
                    continue
                self._extract_table_deps_from_ast(ast, deps)
                self._extract_view_deps_from_objects(stmt_text, default_schema, deps)
        except Exception as e:
            logger.warning(f"Error extracting dependencies: {e}")
        return deps

    def _should_skip_dependency_statement(self, stmt_text: str) -> bool:
        if self._contains_procedural_keywords(stmt_text):
            return True
        if self._contains_oracle_sqlglot_unsupported(stmt_text):
            return True
        return False

    def _extract_table_deps_from_ast(self, ast: exp.Expression, deps: Dict[str, List[str]]) -> None:
        created_names: set[str] = set()
        try:
            if isinstance(ast, exp.Create) and isinstance(ast.this, exp.Table):
                created_table = ast.this
                created_name = created_table.name
                if created_name:
                    created_names.add(created_name.lower())
                created_schema = created_table.args.get("db")
                if created_schema:
                    schema_str = (
                        str(created_schema)
                        if not isinstance(created_schema, str)
                        else created_schema
                    )
                    created_names.add(f"{schema_str.lower()}.{created_name.lower()}")
        except Exception as e:
            logger.debug(f"Could not extract created object names from AST: {e}")

        for table_expr in ast.find_all(exp.Table):
            try:
                table_name = table_expr.name
            except Exception as e:
                logger.debug(f"Could not read table name from AST expression: {e}")
                table_name = None

            if not table_name:
                continue

            schema_expr = table_expr.args.get("db")
            schema_name = (
                str(schema_expr)
                if schema_expr and not isinstance(schema_expr, str)
                else schema_expr
            )
            normalized_table = table_name.lower()
            qualified_name = (
                f"{schema_name.lower()}.{normalized_table}" if schema_name else normalized_table
            )

            if normalized_table in created_names or qualified_name in created_names:
                continue

            if normalized_table not in [name.lower() for name in deps["tables"]]:
                deps["tables"].append(table_name)

            if schema_name and schema_name not in deps["schemas"]:
                deps["schemas"].append(schema_name)

    def _extract_view_deps_from_objects(
        self, stmt_text: str, default_schema: Optional[str], deps: Dict[str, List[str]]
    ) -> None:
        if self.sqlglot_parser is None:
            raise RuntimeError("sqlglot_parser is not initialized")
        try:
            objects = self.sqlglot_parser.extract_objects(stmt_text, default_schema)
        except Exception as extraction_exc:
            logger.debug(
                f"SqlGlot object extraction failed during dependency analysis: {extraction_exc}"
            )
            objects = []

        for obj in objects:
            if obj.object_type.value == "VIEW" and obj.name not in deps["views"]:
                deps["views"].append(obj.name)
            if obj.schema and obj.schema not in deps["schemas"]:
                deps["schemas"].append(obj.schema)

    def _enhance_statement(self, stmt: SqlStatement, default_schema: Optional[str]) -> SqlStatement:
        """Enhance a statement with sqlglot analysis if applicable.

        Args:
            stmt: Statement from regex parser
            default_schema: Default schema name

        Returns:
            Enhanced statement with additional metadata
        """
        # Skip enhancement if sqlglot not available
        if not self.sqlglot_parser:
            return stmt

        # Only enhance pure SQL statements
        if stmt.statement_type not in self.PURE_SQL_TYPES:
            return stmt

        # Skip if contains procedural keywords
        if self._contains_procedural_keywords(stmt.sql_text):
            return stmt

        try:
            # Parse with sqlglot for enhanced object extraction
            sqlglot_result = self.sqlglot_parser.parse_sql(stmt.sql_text, default_schema)

            if sqlglot_result.success and sqlglot_result.statements:
                sqlglot_stmt = sqlglot_result.statements[0]

                # Merge objects from both parsers (sqlglot often more accurate)
                enhanced_objects = self._merge_objects(stmt.objects, sqlglot_stmt.objects)
                enhanced_affected = self._merge_objects(
                    stmt.affected_objects, sqlglot_stmt.affected_objects
                )

                # Create enhanced statement
                return SqlStatement(
                    sql_text=stmt.sql_text,
                    statement_type=stmt.statement_type,
                    objects=enhanced_objects,
                    affected_objects=enhanced_affected,
                    dialect=stmt.dialect,
                    schema=stmt.schema,
                )

        except Exception as e:
            logger.debug(f"Could not enhance statement with sqlglot: {e}")

        # Return original if enhancement fails
        return stmt

    def _contains_procedural_keywords(self, sql_text: str) -> bool:
        """Check if SQL text contains procedural language keywords.

        Args:
            sql_text: SQL text to check

        Returns:
            True if contains procedural keywords
        """
        upper_sql = sql_text.upper()
        return any(keyword in upper_sql for keyword in self.PROCEDURAL_KEYWORDS)

    def _contains_oracle_sqlglot_unsupported(self, sql_text: str) -> bool:
        """Check if SQL contains Oracle-specific syntax that SqlGlot cannot parse.

        SqlGlot's Oracle dialect does not support PARTITION BY REFERENCE, etc.
        When detected, we skip sqlglot and use regex parser only.

        Args:
            sql_text: SQL text to check

        Returns:
            True if contains unsupported Oracle syntax (for Oracle dialect only)
        """
        patterns = self._quirks.sqlglot_unsupported_sql_patterns
        if not patterns:
            return False
        upper_sql = sql_text.upper()
        return any(pattern in upper_sql for pattern in patterns)

    def _merge_objects(
        self, regex_objects: List[SqlObject], sqlglot_objects: List[SqlObject]
    ) -> List[SqlObject]:
        """Merge object lists, preferring sqlglot for duplicates.

        Args:
            regex_objects: Objects from regex parser
            sqlglot_objects: Objects from sqlglot parser

        Returns:
            Merged list of unique objects
        """
        # Create a dict to track unique objects by name
        merged = {}

        # Add regex objects first (skip objects with name "unknown" - parsing fallback)
        for obj in regex_objects:
            if obj.name.lower() != "unknown":
                key = (obj.name.lower(), obj.object_type.value)
                merged[key] = obj

        # Override with sqlglot objects (more accurate)
        for obj in sqlglot_objects:
            key = (obj.name.lower(), obj.object_type.value)
            merged[key] = obj

        return list(merged.values())

    @staticmethod
    def _object_exists(collection: Optional[List[Any]], candidate: SqlObject) -> bool:
        if not collection:
            return False
        candidate_name = candidate.name.lower()
        candidate_schema = (candidate.schema or "").lower()
        for existing in collection:
            if (
                existing.object_type == candidate.object_type
                and existing.name.lower() == candidate_name
                and (existing.schema or "").lower() == candidate_schema
            ):
                return True
        return False

    def _collect_objects(self, result: ParseResult, objects: List[SqlObject]) -> None:
        """Populate ParseResult aggregate collections from statement objects."""
        if not objects:
            return

        for obj in objects:
            entry = _COLLECT_DISPATCH.get(obj.object_type)
            if entry is None:
                continue
            expected_class, get_collection, add_method_name = entry
            if not isinstance(obj, expected_class):
                continue
            if get_collection is not None and self._object_exists(get_collection(result), obj):
                continue
            getattr(result, add_method_name)(obj)

    def _ensure_table_metadata(
        self, stmt: SqlStatement, default_schema: Optional[str], result: ParseResult
    ) -> None:
        sql_text = stmt.sql_text or ""
        # Remove comments first to get the actual SQL statement
        sql_no_comments = re.sub(
            r"/\*.*?\*/", "", sql_text, flags=re.DOTALL
        )  # Remove block comments
        sql_no_comments = re.sub(
            r"--.*?$", "", sql_no_comments, flags=re.MULTILINE
        )  # Remove line comments
        sql_upper = sql_no_comments.strip().upper()
        # Handle both CREATE TABLE and CREATE CONTAINER (CosmosDB)
        if not (sql_upper.startswith("CREATE TABLE") or sql_upper.startswith("CREATE CONTAINER")):
            return

        table_model = self._build_table_model_from_sqlglot(sql_text, default_schema)
        if not table_model:
            table_model = self._build_table_model_from_regex(sql_text, default_schema)
        if not table_model:
            return

        existing = self._find_table(result.tables, table_model.name, table_model.schema)
        if existing:
            self._merge_table_metadata(existing, table_model)
            target_table = existing
        else:
            result.add_table(table_model)
            target_table = table_model

        self._apply_partition_metadata(target_table, sql_text)

    def _ensure_alter_table_metadata(
        self, stmt: SqlStatement, default_schema: Optional[str], result: ParseResult
    ) -> None:
        """Extract constraints from ALTER TABLE statements and add them to existing tables."""
        sql_text = stmt.sql_text or ""
        sql_upper = sql_text.upper().strip()
        if not sql_upper.startswith("ALTER TABLE"):
            return

        try:
            if self.sqlglot_parser:
                constraint_exprs = self._parse_alter_table_via_sqlglot(
                    sql_text, default_schema, result
                )
                if constraint_exprs is not None:
                    return
            # Fallback to regex parsing for dialects without sqlglot support (e.g., DB2)
            self._parse_alter_table_with_regex(sql_text, default_schema, result)
        except Exception as e:
            logger.debug(f"Could not parse ALTER TABLE with sqlglot: {e}")
            try:
                self._parse_alter_table_with_regex(sql_text, default_schema, result)
            except Exception as regex_error:
                logger.debug(f"Could not parse ALTER TABLE with regex: {regex_error}")

    def _parse_alter_table_via_sqlglot(
        self, sql_text: str, default_schema: Optional[str], result: ParseResult
    ) -> Optional[List[SqlConstraint]]:
        """Parse ALTER TABLE via sqlglot. Returns list of applied constraints, or None if not applicable."""
        if self.sqlglot_parser is None:
            raise RuntimeError("sqlglot_parser is not initialized")
        ast = parse_one(sql_text, read=self.sqlglot_parser.sqlglot_dialect)
        if not (isinstance(ast, exp.Alter) and ast.kind == "TABLE"):
            return None

        table_name = None
        table_schema = None
        if isinstance(ast.this, exp.Table):
            table_name = ast.this.name
            table_schema = ast.this.args.get("db") or default_schema
        elif isinstance(ast.this, exp.Schema) and isinstance(ast.this.this, exp.Table):
            table_name = ast.this.this.name
            table_schema = ast.this.name or default_schema

        if not table_name:
            return []

        target_table = self._find_table(result.tables, table_name, table_schema)
        if not target_table:
            target_table = Table(
                name=table_name,
                schema=table_schema,
                dialect=self.dialect,
            )
            result.add_table(target_table)

        all_constraints: List[SqlConstraint] = []
        actions = ast.args.get("actions") or []
        for action in actions:
            if isinstance(action, exp.AddConstraint):
                for constraint_expr in action.expressions:
                    constraints = self._extract_table_constraints_from_sqlglot(constraint_expr)
                    logger.debug(
                        f"Extracted {len(constraints)} constraints from ALTER TABLE for {table_schema}.{table_name}"
                    )
                    self._apply_alter_constraints_to_table(
                        target_table, constraints, table_schema, table_name
                    )
                    all_constraints.extend(constraints)

        return all_constraints

    def _apply_alter_constraints_to_table(
        self,
        table: Table,
        constraints: List[SqlConstraint],
        table_schema: Optional[str],
        table_name: str,
    ) -> None:
        for constraint in constraints:
            logger.debug(
                f"  Constraint: name={constraint.name}, type={constraint.constraint_type}, check_expression={repr(constraint.check_expression)}"
            )
            existing = None
            if constraint.name:
                for existing_const in table.constraints:
                    if (
                        existing_const.name
                        and existing_const.name.lower() == constraint.name.lower()
                    ):
                        existing = existing_const
                        break

            if not existing:
                table.add_constraint(constraint)
                logger.debug(
                    f"  Added constraint {constraint.name} to table {table_schema}.{table_name}"
                )
            elif constraint.check_expression and not existing.check_expression:
                existing.check_expression = constraint.check_expression
                logger.debug(
                    f"  Updated existing constraint {constraint.name} with check expression"
                )

    def _parse_alter_table_with_regex(
        self, sql_text: str, default_schema: Optional[str], result: ParseResult
    ) -> None:
        """Parse ALTER TABLE ADD CONSTRAINT using regex (fallback for DB2 and other dialects without sqlglot)."""
        # Extract table name and schema
        table_match = re.search(
            r"ALTER\s+TABLE\s+(?:(\w+)\.)?(\w+)",
            sql_text,
            re.IGNORECASE,
        )
        if not table_match:
            return

        table_schema = table_match.group(1) or default_schema
        table_name = table_match.group(2)

        # Find or create the table in the result
        target_table = self._find_table(result.tables, table_name, table_schema)
        if not target_table:
            target_table = Table(
                name=table_name,
                schema=table_schema,
                dialect=self.dialect,
            )
            result.add_table(target_table)

        # Extract ADD CONSTRAINT CHECK
        check_match = re.search(
            r"ADD\s+CONSTRAINT\s+(\w+)\s+CHECK\s*\(([^)]+)\)",
            sql_text,
            re.IGNORECASE | re.DOTALL,
        )
        if check_match:
            constraint_name = self._normalize_identifier(check_match.group(1), preserve_case=True)
            check_expression = check_match.group(2).strip()

            # Check if constraint already exists
            existing = None
            for existing_const in target_table.constraints:
                if existing_const.name and existing_const.name.lower() == constraint_name.lower():
                    existing = existing_const
                    break

            if not existing:
                constraint = SqlConstraint(
                    ConstraintType.CHECK,
                    name=constraint_name,
                    check_expression=check_expression,
                    dialect=self.dialect,
                )
                target_table.add_constraint(constraint)
                logger.debug(
                    f"Added CHECK constraint {constraint_name} to table {table_schema}.{table_name} via regex parsing"
                )
            elif check_expression and not existing.check_expression:
                existing.check_expression = check_expression
                logger.debug(
                    f"Updated existing constraint {constraint_name} with check expression via regex parsing"
                )

    def _ensure_view_metadata(
        self, stmt: SqlStatement, default_schema: Optional[str], result: ParseResult
    ) -> None:
        view_model = self._build_view_from_sqlglot(stmt.sql_text or "", default_schema)
        if not view_model:
            return

        for view in result.views or []:
            if view.name == view_model.name and view.schema == view_model.schema:
                if not view.query and view_model.query:
                    view.query = view_model.query
                return

        result.add_view(view_model)

    def _ensure_index_metadata(
        self, stmt: SqlStatement, default_schema: Optional[str], result: ParseResult
    ) -> None:
        index_model = self._build_index_from_sqlglot(stmt.sql_text or "", default_schema)
        if not index_model:
            return

        for index in result.indexes or []:
            if index.name == index_model.name and index.schema == index_model.schema:
                return

        result.add_index(index_model)

    def _ensure_trigger_metadata(
        self, stmt: SqlStatement, default_schema: Optional[str], result: ParseResult
    ) -> None:
        """Extract trigger metadata from CREATE TRIGGER statements."""
        sql_text = stmt.sql_text or ""
        sql_upper = sql_text.upper().strip()
        if not sql_upper.startswith("CREATE"):
            return

        trigger_match = self._parse_trigger_header(sql_text)
        if not trigger_match:
            return

        definer = self._extract_trigger_definer(sql_text)
        self._build_or_update_trigger(stmt, trigger_match, definer, default_schema, result)

    def _find_table(
        self, tables: Optional[List[Table]], name: str, schema: Optional[str]
    ) -> Optional[Table]:
        if not tables:
            return None

        normalized_name = name.lower()
        normalized_schema = (schema or "").lower()
        for table in tables:
            if (
                table.name.lower() == normalized_name
                and (table.schema or "").lower() == normalized_schema
            ):
                return table
        return None

    def _merge_table_metadata(self, target: Table, source: Table) -> None:
        """Merge reconstructed metadata into an existing Table."""
        for column in source.columns:
            if not target.get_column(column.name):
                target.add_column(column)

        for constraint in source.constraints:
            if constraint not in target.constraints:
                target.add_constraint(constraint)

        if source.partition_method and not target.partition_method:
            target.partition_method = source.partition_method
        if source.partition_columns and not target.partition_columns:
            target.partition_columns = source.partition_columns

    def _build_table_model_from_regex(
        self, sql_text: str, default_schema: Optional[str]
    ) -> Optional[Table]:
        """Create a lightweight Table model from a CREATE TABLE or CREATE CONTAINER statement."""
        normalized = sql_text.strip()
        # Handle both CREATE TABLE and CREATE CONTAINER (CosmosDB)
        create_match = re.search(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?"
            r"(?:GLOBAL\s+TEMPORARY\s+)?"
            r"(?:TABLE|CONTAINER)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<identifier>[^\s(]+)",
            normalized,
            flags=re.IGNORECASE,
        )
        if not create_match:
            return None

        identifier = create_match.group("identifier")
        schema, table_name = self._split_identifier(identifier, default_schema)
        table = Table(name=table_name, schema=schema, dialect=self.dialect)

        column_block = self._extract_column_block(normalized, create_match.end())
        if column_block:
            columns, constraints = self._parse_table_definition(column_block)
            for column in columns:
                table.add_column(column)
            for constraint in constraints:
                table.add_constraint(constraint)

        self._apply_partition_metadata(table, normalized)

        # CosmosDB: extract partition key — two syntaxes:
        # 1. User-written migrations: WITH PARTITION KEY /path
        # 2. dblift-generated DDL:    WITH (partitionKey='/path')
        pk_match = re.search(
            r"WITH\s+PARTITION\s+KEY\s+(/[^\s;,()]+)" r"|WITH\s*\(\s*partitionKey\s*=\s*'(/[^']+)'",
            normalized,
            re.IGNORECASE,
        )
        if pk_match:
            table.metadata = {"partition_key": pk_match.group(1) or pk_match.group(2)}

        return table

    def _extract_column_block(self, sql_text: str, start_index: int) -> Optional[str]:
        """Extract the `( ... )` block that defines columns/constraints."""
        remainder = sql_text[start_index:]
        first_paren = remainder.find("(")
        if first_paren == -1:
            return None

        depth = 0
        in_single = False
        in_double = False
        block_chars: List[str] = []
        for char in remainder[first_paren + 1 :]:
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double

            if in_single or in_double:
                block_chars.append(char)
                continue

            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    break
                depth -= 1
                block_chars.append(char)
                continue

            block_chars.append(char)

        block = "".join(block_chars).strip()
        return block or None

    def _parse_table_definition(
        self, definition: str
    ) -> Tuple[List[SqlColumn], List[SqlConstraint]]:
        columns: List[SqlColumn] = []
        constraints: List[SqlConstraint] = []

        for item in self._split_definition_items(definition):
            parsed_column, inline_constraint = self._parse_column_definition(item)
            if parsed_column:
                columns.append(parsed_column)
                if inline_constraint:
                    constraints.append(inline_constraint)
                continue

            constraint = self._parse_table_constraint(item)
            if constraint:
                constraints.append(constraint)

        return columns, constraints

    def _split_definition_items(self, definition: str) -> List[str]:
        items: List[str] = []
        current: List[str] = []
        depth = 0
        in_single = False
        in_double = False

        for char in definition:
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif not in_single and not in_double:
                if char == "(":
                    depth += 1
                elif char == ")":
                    if depth > 0:
                        depth -= 1

            if char == "," and depth == 0 and not in_single and not in_double:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
            else:
                current.append(char)

        remainder = "".join(current).strip()
        if remainder:
            items.append(remainder)
        return items

    def _parse_column_definition(
        self, definition: str
    ) -> Tuple[Optional[SqlColumn], Optional[SqlConstraint]]:
        leading = definition.lstrip().upper()
        if leading.startswith("CONSTRAINT") or leading.startswith("PRIMARY KEY"):
            return None, None

        match = re.match(r"\s*([`\"\[\]\w\.]+)\s+(.*)", definition, re.IGNORECASE)
        if not match:
            return None, None

        column_name = self._normalize_identifier(match.group(1), preserve_case=False)
        remainder = match.group(2).strip()
        if not remainder:
            return None, None

        tokens = remainder.split()
        data_type_tokens: List[str] = []
        constraint_start = len(tokens)
        constraint_markers = {
            "NOT",
            "NULL",
            "PRIMARY",
            "REFERENCES",
            "CONSTRAINT",
            "UNIQUE",
            "CHECK",
            "DEFAULT",
            "FOREIGN",
        }

        for idx, token in enumerate(tokens):
            normalized = token.upper()
            if normalized in constraint_markers:
                constraint_start = idx
                break
            data_type_tokens.append(token)

        if not data_type_tokens:
            return None, None

        data_type = " ".join(data_type_tokens)
        constraint_clause = (
            " ".join(tokens[constraint_start:]) if constraint_start < len(tokens) else ""
        )
        constraint_clause_upper = constraint_clause.upper()

        is_nullable = "NOT NULL" not in constraint_clause_upper
        is_primary_key = "PRIMARY KEY" in constraint_clause_upper

        column = SqlColumn(
            name=column_name,
            data_type=data_type,
            is_nullable=is_nullable,
            is_primary_key=is_primary_key,
            dialect=self.dialect,
        )

        inline_constraint = None
        if is_primary_key:
            inline_constraint = SqlConstraint(
                ConstraintType.PRIMARY_KEY, column_names=[column_name], dialect=self.dialect
            )

        return column, inline_constraint

    def _parse_table_constraint(self, definition: str) -> Optional[SqlConstraint]:
        normalized = definition.strip()
        upper = normalized.upper()

        if "PRIMARY KEY" not in upper:
            return None

        name = None
        if upper.startswith("CONSTRAINT"):
            parts = normalized.split(None, 2)
            if len(parts) >= 3:
                name = self._normalize_identifier(parts[1], preserve_case=True)
                normalized = parts[2]
                upper = normalized.upper()

        columns = self._extract_identifier_list(normalized)
        return SqlConstraint(
            ConstraintType.PRIMARY_KEY, name=name, column_names=columns, dialect=self.dialect
        )

    def _extract_identifier_list(self, expression: str) -> List[str]:
        match = re.search(r"\((.*?)\)", expression, flags=re.DOTALL)
        if not match:
            return []

        raw = match.group(1)
        identifiers = []
        for part in raw.split(","):
            cleaned = self._normalize_identifier(part, preserve_case=False)
            if cleaned:
                identifiers.append(cleaned)
        return identifiers

    def _split_identifier(
        self, identifier: str, default_schema: Optional[str]
    ) -> Tuple[Optional[str], str]:
        cleaned = identifier.strip()
        if "." in cleaned:
            schema_part, table_part = cleaned.split(".", 1)
        else:
            schema_part, table_part = None, cleaned

        schema = (
            self._normalize_identifier(schema_part, preserve_case=False)
            if schema_part
            else (default_schema.upper() if default_schema else None)
        )
        table_name = self._normalize_identifier(table_part, preserve_case=False)
        return schema, table_name

    def _normalize_identifier(self, identifier: Optional[str], preserve_case: bool) -> str:
        if identifier is None:
            return ""

        trimmed = identifier.strip().strip('"').strip("`")
        if trimmed.startswith("[") and trimmed.endswith("]"):
            trimmed = trimmed[1:-1]

        if "." in trimmed:
            trimmed = trimmed.split(".")[-1]

        return trimmed if preserve_case else trimmed.upper()

    def _apply_partition_metadata(self, table: Table, sql_text: str) -> None:
        from core.sql_parser._partition_handler import apply_partition_metadata

        apply_partition_metadata(table, sql_text)
