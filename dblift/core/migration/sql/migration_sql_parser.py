"""Stateless SQL splitting and the compatibility semicolon fallback."""

import os
from typing import Any, List, Optional

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.logger import Log
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


def _default_splitter_dialect() -> str:
    """Registry-derived generic dialect for statement splitting (ADR-26 E5).

    Used only on the no-dialect fallback path where no dialect could be
    resolved from explicit args, config, or environment. The statement
    splitter still needs *a* relational dialect for its regex tokenizer;
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
    """Resolve the legacy splitting fallback without mutating migration metadata."""
    if dialect:
        return dialect
    if config and hasattr(config, "database") and config.database.type:
        dialect = config.database.type.lower()
        log.info(f"Using dialect '{dialect}' from config")
    if not dialect:
        db_type = os.environ.get("DBLIFT_DATABASE_TYPE")
        if db_type:
            dialect = db_type.lower()
            log.info(f"Using dialect '{dialect}' from environment variable")
    if not dialect:
        log.warning("No dialect available from config, defaulting to simple parser")
        dialect = _default_splitter_dialect()
    return dialect


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
    except UnsupportedMetaCommandError:
        # A deliberate refusal, not a splitting failure -- the semicolon
        # fallback below has no notion of meta-commands either and would
        # reproduce the exact defect the refusal exists to surface instead.
        raise
    except Exception as exc:
        return fallback_migration_sql(content, log, exc)
