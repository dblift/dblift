"""Execution-time SQL statement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ExecutionStatement:
    """A SQL statement plus transaction metadata used by the execution engine."""

    sql: str
    statement_type: str = "UNKNOWN"
    can_execute_in_transaction: bool = True
    transaction_reason: Optional[str] = None


def classify_execution_statement(
    sql: str, *, dialect: str, statement_type: str = "UNKNOWN"
) -> ExecutionStatement:
    """Classify transaction metadata for high-confidence dialect-specific cases."""
    from dblift.db.provider_registry import ProviderRegistry

    normalized = re.sub(r"\s+", " ", sql.strip()).upper()
    quirks = ProviderRegistry.get_quirks(dialect.lower())

    for pattern, reason in quirks.non_transactional_sql_patterns:
        if re.match(pattern, normalized):
            return ExecutionStatement(
                sql=sql,
                statement_type=statement_type,
                can_execute_in_transaction=False,
                transaction_reason=reason,
            )

    return ExecutionStatement(sql=sql, statement_type=statement_type)
