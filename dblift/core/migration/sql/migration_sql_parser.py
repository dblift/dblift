"""Stateless migration SQL splitting through the dialect scanner."""

import os
from typing import Any, List, Optional

from dblift.core.constants import ENV_PREFIX
from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.logger import Log
from dblift.core.migration.sql.execution_contracts import ExecutionSqlParser

#: What makes a split statement empty. Any other white space character is one its dialect keeps.
EMPTY_STATEMENT_BLANKS = " \t\r\n"


def _default_splitter_dialect() -> str:
    """Registry-derived generic dialect for statement splitting (ADR-26 E5).

    Used only when no dialect could be
    resolved from explicit args, config, or environment. The statement
    splitter still needs *a* relational dialect for its script scanner;
    we take the first relational native dialect the plugin registry
    advertises (sorted by name) so no dialect-name literal is hardcoded.
    """
    from dblift.db.provider_registry import ProviderRegistry

    relational = sorted(
        p.name
        for p in ProviderRegistry.list_plugins()
        if ProviderRegistry.is_native_dialect(p.name)
        and ProviderRegistry.get_quirks(p.name).sqlglot_dialect
    )
    return relational[0] if relational else ""


def resolve_migration_sql_dialect(dialect: Optional[str], config: Any, log: Log) -> str:
    """Resolve a dialect for splitting without mutating migration metadata."""
    if dialect:
        return dialect
    if config and hasattr(config, "database") and config.database.type:
        dialect = config.database.type.lower()
        log.info(f"Using dialect '{dialect}' from config")
    if not dialect:
        db_type = os.environ.get(f"{ENV_PREFIX}DATABASE_TYPE")
        if db_type:
            dialect = db_type.lower()
            log.info(f"Using dialect '{dialect}' from environment variable")
    if not dialect:
        log.warning("No dialect available from config, using a registered dialect scanner")
        dialect = _default_splitter_dialect()
    return dialect


def parse_migration_sql(
    analyzer: ExecutionSqlParser, content: str, log: Log, *, for_analysis: bool = False
) -> List[str]:
    """Split the supplied content without modifying migration state.

    ``for_analysis`` asks for the statements a statement-by-statement reader needs (a T-SQL batch
    divided) instead of what execution sends.
    """
    try:
        statements = (
            analyzer.split_statements_for_analysis(content)
            if for_analysis
            else analyzer.split_statements(content)
        )
        log.debug(f"SqlAnalyzer split returned {len(statements)} statements")
        return [statement for statement in statements if statement.strip(EMPTY_STATEMENT_BLANKS)]
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError):
        # Preserve the dialect scanner's deliberate refusal and its location.
        raise
    except Exception as exc:
        raise UnsafeStatementSplitError(f"statement splitter failed: {exc}") from exc
