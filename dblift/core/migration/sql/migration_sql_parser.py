"""Stateless SQL splitting and the compatibility semicolon fallback."""

from typing import List

from dblift.core.logger import Log
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def fallback_migration_sql(content: str, log: Log, error: Exception) -> List[str]:
    """Preserve SQL parsing's fallback for analyzer construction or splitting failures."""
    log.warning(f"Error using SqlAnalyzer: {error}. Falling back to simple semicolon-based parser.")
    statements = [statement.strip() for statement in content.split(";") if statement.strip()]
    log.debug(f"Fallback parser produced {len(statements)} statements")
    return statements


def parse_migration_sql(analyzer: SqlAnalyzer, content: str, log: Log) -> List[str]:
    """Split the supplied content without modifying migration state."""
    try:
        statements = analyzer.split_statements(content)
        log.debug(f"SqlAnalyzer split returned {len(statements)} statements")
        return [statement for statement in statements if statement.strip()]
    except Exception as exc:
        return fallback_migration_sql(content, log, exc)
