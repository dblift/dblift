"""Single entry point for rendering Table DDL.

All human-facing SQL text routes through ``render_table_ddl``. Same path for HTML
diff display, JSON exports, and drift SQL. No sqlglot transpilation — native
dialect types preserved (``serial``, ``int4``, ``numeric``, ``timestamptz``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from core.sql_generator.generator_factory import SqlGeneratorFactory

if TYPE_CHECKING:
    from core.sql_model.table import Table


def render_table_ddl(
    table: "Table",
    *,
    dialect: str,
    format_for_compare: bool = False,
) -> str:
    """Render a Table to its dialect-specific CREATE TABLE statement.

    Args:
        table: Table object to render.
        dialect: SQL dialect (postgresql, mysql, sqlserver, oracle, db2, sqlite).
        format_for_compare: When True, applies textual normalization for stable
            line-by-line diff display: rstrips each line, collapses runs of blank
            lines, ensures trailing semicolon. No sqlglot, no type rewriting.

    Returns:
        CREATE TABLE SQL as string. Empty string if generator returns nothing.
    """
    generator = SqlGeneratorFactory.create(dialect)
    if hasattr(generator, "generate_create_statement"):
        sql = str(generator.generate_create_statement(table))
    else:
        sql = BasicTableDdlGenerator(table).generate_create_statement()

    if format_for_compare:
        sql = _format_for_compare(sql)
    return sql


_BLANK_LINE_RUN = re.compile(r"\n{3,}")


def _format_for_compare(sql: str) -> str:
    """Textual normalization for diff display. No SQL transpilation."""
    if not sql:
        return ""
    lines = [line.rstrip() for line in sql.splitlines()]
    sql = "\n".join(lines).strip()
    sql = _BLANK_LINE_RUN.sub("\n\n", sql)
    if not sql.endswith(";"):
        sql += ";"
    return sql
