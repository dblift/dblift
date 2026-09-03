"""Façade for the SQL Model base classes.

Historically ``dblift.core.sql_model.base`` was a single 1153-line module that held
``SqlObject``, ``SqlColumn``, ``SqlConstraint``, ``SqlStatement`` and
``ParseResult`` together with their supporting enums. PR-H13 split each of
those classes into its own ``_base_*`` sibling module. This file is now a
thin façade that re-exports every public name so existing import sites
(``from core.sql_model.base import SqlObject``, etc.) keep working unchanged.

Add new SQL model primitives in a dedicated ``_base_*`` module and re-export
them here.
"""

from __future__ import annotations

from dblift.core.sql_model._base_parse_result import ParseResult
from dblift.core.sql_model._base_sql_column import SqlColumn
from dblift.core.sql_model._base_sql_constraint import (  # noqa: F401
    ConstraintType,
    SqlConstraint,
    _norm_constraint_deferrable,
    _norm_constraint_enabled,
    get_constraint_type_name,
)
from dblift.core.sql_model._base_sql_object import (
    SqlObject,
    SqlObjectType,
    get_object_type_name,
)
from dblift.core.sql_model._base_sql_statement import SqlStatement, SqlStatementType

__all__ = [
    "ConstraintType",
    "ParseResult",
    "SqlColumn",
    "SqlConstraint",
    "SqlObject",
    "SqlObjectType",
    "SqlStatement",
    "SqlStatementType",
    "get_constraint_type_name",
    "get_object_type_name",
]
