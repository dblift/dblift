"""Execution-time SQL statement metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes


@dataclass(frozen=True)
class ExecutionStatement:
    """A SQL statement plus transaction metadata used by the execution engine."""

    sql: str
    statement_type: str = "UNKNOWN"
    can_execute_in_transaction: bool = True
    transaction_reason: Optional[str] = None


def is_comment_only_statement(sql: str, *, nested_block_comments: bool = False) -> bool:
    """True if *sql* has no executable tokens after removing block and line comments.

    MySQL/MariaDB executable comment directives (``/*!...*/``, ``/*M!...*/``) are not
    comments the server skips — it runs their contents — so they are excluded from the
    strip and never count as "comment only".

    Pass ``nested_block_comments=True`` for a dialect whose block comments nest
    (its tokenizer's ``NESTED_BLOCK_COMMENTS``): ``/* a /* b */ c */`` is then one
    comment, stripped by the same scanner the dialect parsers use. MySQL/MariaDB
    comments do not nest, so their directives always take the default path.
    """

    body = sql.strip()
    if not body:
        return True
    if nested_block_comments:
        return not strip_comments_preserving_quotes(
            body, line_prefixes=["--"], has_block_comments=True, nested_block_comments=True
        )
    body = re.sub(r"/\*(?!!|M!).*?\*/", "", body, flags=re.DOTALL)
    body = re.sub(r"--.*?$", "", body, flags=re.MULTILINE)
    return not body.strip()


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
