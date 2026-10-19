"""SQL text inspection helpers used by migration operations."""

from __future__ import annotations

from typing import Any


def _heuristic_statement_count_from_sql(sql_text: str) -> int:
    """Count lines that look like standalone SQL statements (heuristic)."""
    return sum(
        1
        for line in sql_text.split("\n")
        if line.strip() and not line.strip().startswith("--") and line.strip().endswith(";")
    )


def _apply_sql_script_warning_scan(
    result: Any,
    sql_text: str,
) -> None:
    """Set manual-review flag and collect per-line warnings from generated SQL text."""
    sql_lower = sql_text.lower()
    if "warning" in sql_lower or "requires manual review" in sql_lower:
        result.requires_manual_review = True
        for line in sql_text.split("\n"):
            if "warning" in line.lower():
                warning_msg = line.strip().lstrip("--").strip()
                if warning_msg:
                    result.add_warning(warning_msg)
