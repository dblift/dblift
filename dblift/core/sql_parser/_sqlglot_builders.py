"""SqlGlot-based model builders extracted from ``HybridParser``.

The mixin keeps the public/private method names unchanged so callers
inside ``HybridParser`` continue to use ``self._build_table_model_from_sqlglot``
etc. without modification. Attributes consumed (``self.dialect``,
``self.sqlglot_parser``, ``self._quirks``) and helpers
(``self._normalize_identifier``) are supplied by the composing class.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional, Tuple

from sqlglot import exp, parse_one

from dblift.core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlColumn,
    SqlConstraint,
    SqlStatement,
)
from dblift.core.sql_model.index import Index
from dblift.core.sql_model.table import Table
from dblift.core.sql_model.trigger import Trigger
from dblift.core.sql_model.view import View

if TYPE_CHECKING:
    from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
    from dblift.db.base_quirks import BaseQuirks

logger = logging.getLogger(__name__)


class _TriggerHeader(NamedTuple):
    """Parsed regex projection of a ``CREATE TRIGGER`` statement header."""

    schema: Optional[str]
    name: str
    timing: Optional[str]
    event: Optional[str]
    table_name: str


class _SqlglotBuildersMixin:
    """Build ``Table`` / ``View`` / ``Index`` / ``Trigger`` models from sqlglot ASTs.

    Requires the composing class to expose: ``dialect``, ``sqlglot_parser``,
    ``_quirks``, and a ``_normalize_identifier(name, *, preserve_case)`` helper.
    """

    # The composing class supplies these — declared here for mypy clarity.
    dialect: str
    sqlglot_parser: Optional["SqlGlotParser"]
    _quirks: "BaseQuirks"

    def _normalize_identifier(  # pragma: no cover - abstract hook
        self, identifier: Optional[str], preserve_case: bool
    ) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------

    def _parse_trigger_header(self, sql: str) -> Optional[re.Match]:
        return re.search(
            r"CREATE\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?TRIGGER\s+"
            r"(?:([a-zA-Z_][a-zA-Z0-9_]*)\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s+"
            r"(BEFORE|AFTER)\s+"
            r"(INSERT|UPDATE|DELETE)\s+"
            r"ON\s+"
            r"([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)",
            sql,
            re.IGNORECASE,
        )

    def _extract_trigger_definer(self, sql: str) -> Optional[str]:
        if not self._quirks.trigger_supports_definer_clause:
            return None
        definer_match = re.search(
            r"DEFINER\s*=\s*([^@\s]+@[^\s]+)",
            sql,
            re.IGNORECASE,
        )
        return definer_match.group(1) if definer_match else None

    def _build_or_update_trigger(
        self,
        stmt: SqlStatement,
        match: re.Match,
        definer: Optional[str],
        default_schema: Optional[str],
        result: ParseResult,
    ) -> None:
        header = self._parse_trigger_match(match, default_schema)
        definition = self._extract_trigger_definition(stmt.sql_text or "")
        existing = self._find_matching_trigger(result.triggers, header)
        if existing is not None:
            self._merge_trigger_metadata(existing, header, definition, definer)
        else:
            result.add_trigger(self._build_trigger_from_header(header, definition, definer))

    def _parse_trigger_match(
        self, match: re.Match, default_schema: Optional[str]
    ) -> "_TriggerHeader":
        """Project a ``CREATE TRIGGER`` regex match into a typed header.

        Group 5 (the table-schema) is intentionally read and discarded:
        the legacy code did the same (``match.group(5) or default_schema``
        was an unassigned expression). The ``Trigger`` model carries a
        single ``schema`` field (the trigger's own schema), not the
        owning table's. Wiring group 5 in would be a separate behavior
        change and is tracked outside this complexity refactor.
        """
        return _TriggerHeader(
            schema=match.group(1) or default_schema,
            name=match.group(2) or "",
            timing=match.group(3).upper() if match.group(3) else None,
            event=match.group(4).upper() if match.group(4) else None,
            table_name=match.group(6) or "",
        )

    def _extract_trigger_definition(self, sql_text: str) -> Optional[str]:
        """Return the trigger body following ``FOR EACH ROW``, or ``None``."""
        match = re.search(
            r"FOR\s+EACH\s+ROW\s+(.*?)(?:;|$)",
            sql_text,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        return match.group(1).strip().rstrip(";")

    @staticmethod
    def _find_matching_trigger(
        triggers: Optional[List[Trigger]], header: "_TriggerHeader"
    ) -> Optional[Trigger]:
        """Return the trigger in *triggers* matching ``(name, table, schema)``.

        Case-insensitive on all three keys to mirror the previous inline
        comparison.
        """
        if not triggers:
            return None
        target_name = header.name.lower()
        target_table = header.table_name.lower()
        target_schema = (header.schema or "").lower()
        for trigger in triggers:
            if (
                trigger.name.lower() == target_name
                and trigger.table_name.lower() == target_table
                and (trigger.schema or "").lower() == target_schema
            ):
                return trigger
        return None

    @staticmethod
    def _merge_trigger_metadata(
        existing: Trigger,
        header: "_TriggerHeader",
        definition: Optional[str],
        definer: Optional[str],
    ) -> None:
        """Fill in missing fields on *existing* without overwriting set values."""
        if header.timing and not existing.timing:
            existing.timing = header.timing
        if header.event and not existing.events:
            existing.events = [header.event]
        if header.table_name and not existing.table_name:
            existing.table_name = header.table_name
        if definition and not existing.definition:
            existing.definition = definition
        if definer and not getattr(existing, "definer", None):
            existing.definer = definer  # type: ignore[attr-defined]

    def _build_trigger_from_header(
        self,
        header: "_TriggerHeader",
        definition: Optional[str],
        definer: Optional[str],
    ) -> Trigger:
        """Construct a fresh ``Trigger`` from the parsed header + body + definer."""
        return Trigger(
            name=header.name,
            table_name=header.table_name,
            schema=header.schema,
            timing=header.timing,
            events=[header.event] if header.event else [],
            orientation="ROW",
            definition=definition,
            dialect=self.dialect,
            definer=definer,
        )

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _build_table_model_from_sqlglot(
        self, sql_text: str, default_schema: Optional[str]
    ) -> Optional[Table]:
        if not self.sqlglot_parser:
            return None

        try:
            ast = parse_one(sql_text, read=self.sqlglot_parser.sqlglot_dialect)
        except Exception as e:
            logger.debug(f"sqlglot could not parse TABLE statement: {e}")
            return None

        if not isinstance(ast, exp.Create) or ast.kind != "TABLE":
            return None

        schema_expr = ast.this
        if not isinstance(schema_expr, exp.Schema):
            return None

        table_expr = schema_expr.this
        if not isinstance(table_expr, exp.Table):
            return None

        schema_name = table_expr.db or default_schema
        table_name = self._normalize_identifier(table_expr.name, preserve_case=True)
        normalized_schema = (
            self._normalize_identifier(schema_name, preserve_case=True) if schema_name else None
        )

        columns: List[SqlColumn] = []
        constraints: List[SqlConstraint] = []
        inline_constraints: List[SqlConstraint] = []

        for expression in schema_expr.expressions or []:
            if isinstance(expression, exp.ColumnDef):
                column, additional = self._column_from_sqlglot(expression)
                columns.append(column)
                inline_constraints.extend(additional)

        constraints.extend(inline_constraints)
        constraints.extend(self._extract_table_constraints_from_sqlglot(schema_expr))

        pk_columns = [column.name for column in columns if column.is_primary_key]
        has_pk_constraint = any(
            constraint.constraint_type == ConstraintType.PRIMARY_KEY for constraint in constraints
        )
        if pk_columns and not has_pk_constraint:
            constraints.append(
                SqlConstraint(
                    ConstraintType.PRIMARY_KEY,
                    column_names=pk_columns,
                    dialect=self.dialect,
                )
            )

        for column in columns:
            if column.is_unique:
                constraints.append(
                    SqlConstraint(
                        ConstraintType.UNIQUE,
                        column_names=[column.name],
                        dialect=self.dialect,
                    )
                )

        table = Table(
            name=table_name,
            schema=normalized_schema,
            columns=columns,
            constraints=constraints,
            dialect=self.dialect,
        )
        return table

    def _column_from_sqlglot(
        self, column_def: exp.ColumnDef
    ) -> Tuple[SqlColumn, List[SqlConstraint]]:
        column_name = self._normalize_identifier(
            self._expression_name(column_def.this), preserve_case=True
        )
        data_type_expr = column_def.args.get("kind")
        data_type = (
            data_type_expr.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
            if data_type_expr and self.sqlglot_parser
            else "UNKNOWN"
        )

        is_nullable = True
        is_primary_key = False
        is_unique = False
        default_value = None
        inline_constraints: List[SqlConstraint] = []

        for constraint in column_def.args.get("constraints") or []:
            kind = constraint.args.get("kind")
            if isinstance(kind, exp.NotNullColumnConstraint):
                is_nullable = False
            elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
                is_primary_key = True
                is_nullable = False
            elif isinstance(kind, exp.UniqueColumnConstraint):
                is_unique = True
            elif isinstance(kind, exp.DefaultColumnConstraint):
                if kind.this and self.sqlglot_parser:
                    default_value = kind.this.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
            elif isinstance(kind, exp.Reference):
                fk = self._build_foreign_key_constraint([column_name], kind)
                if fk:
                    inline_constraints.append(fk)
            elif isinstance(kind, exp.CheckColumnConstraint):
                check_sql = (
                    kind.this.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
                    if kind.this and self.sqlglot_parser
                    else None
                )
                inline_constraints.append(
                    SqlConstraint(
                        ConstraintType.CHECK,
                        column_names=[column_name],
                        check_expression=check_sql,
                        dialect=self.dialect,
                    )
                )

        column = SqlColumn(
            name=column_name,
            data_type=data_type,
            is_nullable=is_nullable,
            is_primary_key=is_primary_key,
            is_unique=is_unique,
            default_value=default_value,
            dialect=self.dialect,
        )

        return column, inline_constraints

    def _extract_table_constraints_from_sqlglot(
        self, constraint_expr: exp.Expression
    ) -> List[SqlConstraint]:
        constraints: List[SqlConstraint] = []
        if not self.sqlglot_parser:
            return constraints

        constraint_name, expressions = self._resolve_constraint_expressions(constraint_expr)

        for expression in expressions:
            constraint_name, inner_expressions = self._unwrap_constraint_expression(
                expression, constraint_name
            )
            for inner in inner_expressions:
                constraint = None
                if isinstance(inner, (exp.Check, exp.CheckColumnConstraint)):
                    constraint = self._extract_check_constraint_from_sqlglot(inner, constraint_name)
                elif isinstance(inner, exp.PrimaryKey):
                    constraint = self._extract_pk_from_sqlglot(inner, constraint_name)
                elif isinstance(inner, exp.ForeignKey):
                    constraint = self._extract_fk_from_sqlglot(inner, constraint_name)
                elif isinstance(inner, exp.UniqueColumnConstraint):
                    constraint = self._extract_unique_from_sqlglot(inner, constraint_name)
                if constraint is not None:
                    constraints.append(constraint)

        return constraints

    def _resolve_constraint_expressions(
        self, constraint_expr: exp.Expression
    ) -> Tuple[Optional[str], list]:
        constraint_name: Optional[str] = None
        if isinstance(constraint_expr, exp.Schema):
            return None, constraint_expr.expressions or []
        elif isinstance(constraint_expr, exp.Constraint):
            if constraint_expr.this:
                if hasattr(constraint_expr.this, "name"):
                    constraint_name = self._normalize_identifier(
                        self._expression_name(constraint_expr.this), preserve_case=True
                    )
                else:
                    constraint_name = self._normalize_identifier(
                        str(constraint_expr.this), preserve_case=True
                    )
            return constraint_name, constraint_expr.expressions or []
        elif isinstance(constraint_expr, (exp.Check, exp.PrimaryKey, exp.ForeignKey)):
            return None, [constraint_expr]
        return None, [constraint_expr]

    def _unwrap_constraint_expression(
        self, expression: exp.Expression, constraint_name: Optional[str]
    ) -> Tuple[Optional[str], list]:
        if isinstance(expression, exp.Constraint):
            constraint_name = (
                self._normalize_identifier(
                    self._expression_name(expression.this), preserve_case=True
                )
                if expression.this and hasattr(expression.this, "name")
                else constraint_name
            )
            if not constraint_name and hasattr(expression, "this"):
                constraint_name = (
                    self._normalize_identifier(str(expression.this), preserve_case=True)
                    if expression.this
                    else None
                )
            return constraint_name, expression.expressions or []
        return constraint_name, [expression]

    def _extract_check_constraint_from_sqlglot(
        self, inner: exp.Expression, constraint_name: Optional[str]
    ) -> SqlConstraint:
        if self.sqlglot_parser is None:
            raise RuntimeError("sqlglot_parser is not initialized")
        check_sql = None
        if hasattr(inner, "this") and inner.this:
            if hasattr(inner.this, "sql"):
                check_sql = inner.this.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
            else:
                check_sql = str(inner.this)
        else:
            check_sql = inner.sql(dialect=self.sqlglot_parser.sqlglot_dialect)

        return SqlConstraint(
            ConstraintType.CHECK,
            name=constraint_name,
            check_expression=check_sql,
            dialect=self.dialect,
        )

    def _extract_pk_from_sqlglot(
        self, inner: exp.PrimaryKey, constraint_name: Optional[str]
    ) -> SqlConstraint:
        column_names = [
            self._normalize_identifier(
                self._expression_name(
                    ordered.this if isinstance(ordered, exp.Ordered) else ordered
                ),
                preserve_case=True,
            )
            for ordered in inner.expressions or []
        ]
        return SqlConstraint(
            ConstraintType.PRIMARY_KEY,
            name=constraint_name,
            column_names=column_names,
            dialect=self.dialect,
        )

    def _extract_fk_from_sqlglot(
        self, inner: exp.ForeignKey, constraint_name: Optional[str]
    ) -> Optional[SqlConstraint]:
        column_names = [
            self._normalize_identifier(self._expression_name(identifier), preserve_case=True)
            for identifier in inner.args.get("expressions") or []
        ]
        return self._build_foreign_key_constraint(
            column_names, inner.args.get("reference"), constraint_name
        )

    def _extract_unique_from_sqlglot(
        self, inner: exp.UniqueColumnConstraint, constraint_name: Optional[str]
    ) -> SqlConstraint:
        schema = inner.this if isinstance(inner.this, exp.Schema) else None
        unique_columns = [
            self._normalize_identifier(self._expression_name(identifier), preserve_case=True)
            for identifier in (schema.expressions if schema else [])
        ]
        return SqlConstraint(
            ConstraintType.UNIQUE,
            name=constraint_name,
            column_names=unique_columns,
            dialect=self.dialect,
        )

    def _build_foreign_key_constraint(
        self,
        column_names: List[str],
        reference: Optional[exp.Expression],
        constraint_name: Optional[str] = None,
    ) -> Optional[SqlConstraint]:
        if not isinstance(reference, exp.Reference):
            return None

        schema_expr = reference.this
        if not isinstance(schema_expr, exp.Schema):
            return None

        table_expr = schema_expr.this
        if not isinstance(table_expr, exp.Table):
            return None

        reference_table = self._normalize_identifier(table_expr.name, preserve_case=True)
        reference_schema = (
            self._normalize_identifier(table_expr.db, preserve_case=True) if table_expr.db else None
        )
        reference_columns = [
            self._normalize_identifier(self._expression_name(identifier), preserve_case=True)
            for identifier in schema_expr.expressions or []
        ]

        constraint = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            name=constraint_name,
            column_names=column_names,
            reference_table=reference_table,
            reference_columns=reference_columns,
            dialect=self.dialect,
        )
        if reference_schema:
            constraint.reference_schema = reference_schema
        return constraint

    def _expression_name(self, expression: Any) -> str:
        if isinstance(expression, exp.Identifier):
            return str(expression.this)
        if isinstance(expression, exp.Column):
            return self._expression_name(expression.this)
        if isinstance(expression, exp.Ordered):
            return self._expression_name(expression.this)
        return (
            expression.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
            if hasattr(expression, "sql") and self.sqlglot_parser
            else str(expression)
        )

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _build_index_from_sqlglot(
        self, sql_text: str, default_schema: Optional[str]
    ) -> Optional[Index]:
        if not self.sqlglot_parser:
            return None

        try:
            ast = parse_one(sql_text, read=self.sqlglot_parser.sqlglot_dialect)
        except Exception as e:
            logger.debug(f"sqlglot could not parse INDEX statement: {e}")
            return None

        if not isinstance(ast, exp.Create) or ast.kind != "INDEX":
            return None

        index_expr = ast.this
        if not isinstance(index_expr, exp.Index):
            return None

        name_expr = index_expr.this
        index_name = self._normalize_identifier(
            self._expression_name(name_expr), preserve_case=True
        )

        table_expr = index_expr.args.get("table")
        if not isinstance(table_expr, exp.Table):
            return None

        table_name = self._normalize_identifier(table_expr.name, preserve_case=True)
        table_schema = (
            self._normalize_identifier(table_expr.db, preserve_case=True)
            if table_expr.db
            else default_schema
        )

        params = index_expr.args.get("params")
        column_exprs = params.args.get("columns") if params else None
        columns = [
            self._normalize_identifier(
                self._expression_name(
                    ordered.this if isinstance(ordered, exp.Ordered) else ordered
                ),
                preserve_case=True,
            )
            for ordered in (column_exprs or [])
        ]

        if not columns:
            return None

        unique = bool(ast.args.get("unique"))

        return Index(
            name=index_name,
            table_name=table_name,
            columns=columns,
            schema=None,
            table_schema=table_schema,
            unique=unique,
            dialect=self.dialect,
        )

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    def _build_view_from_sqlglot(
        self, sql_text: str, default_schema: Optional[str]
    ) -> Optional[View]:
        if not self.sqlglot_parser:
            return None

        try:
            ast = parse_one(sql_text, read=self.sqlglot_parser.sqlglot_dialect)
        except Exception as e:
            logger.debug(f"sqlglot could not parse VIEW statement: {e}")
            return None

        if not isinstance(ast, exp.Create) or ast.kind != "VIEW":
            return None

        table_expr = ast.this
        if not isinstance(table_expr, exp.Table):
            return None

        view_name = self._normalize_identifier(table_expr.name, preserve_case=True)
        view_schema = (
            self._normalize_identifier(table_expr.db, preserve_case=True)
            if table_expr.db
            else default_schema
        )
        materialized = "MATERIALIZED VIEW" in (sql_text.upper())

        query_expr = ast.args.get("expression")
        query_sql = (
            query_expr.sql(dialect=self.sqlglot_parser.sqlglot_dialect)
            if query_expr and self.sqlglot_parser
            else None
        )

        return View(
            name=view_name,
            schema=view_schema,
            query=query_sql,
            materialized=materialized,
            dialect=self.dialect,
        )
