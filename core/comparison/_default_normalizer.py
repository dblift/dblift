"""Pure-function normalizers for default-value and CHECK-expression comparison.

Extracted from :class:`core.comparison.table_comparator.TableComparator`
to keep the orchestrator focused on diff logic. Both functions are
side-effect-free and reference no instance state, so they are exposed
as module-level callables. ``TableComparator`` keeps thin wrapper
methods (``_normalize_default_value`` / ``_normalize_expression``) that
delegate here, preserving the public surface used by existing tests.

Function names are scoped (``normalize_column_default``,
``normalize_check_expression``) to avoid colliding with the more general
``normalize_expression`` already exported by
:mod:`core.comparison.comparison_utils` — that one is consumed by the
event/function/procedure comparators and has different semantics.
"""

from __future__ import annotations

import re
from typing import Optional

from core.comparison.comparison_utils import (
    strip_boolean_wrappers,
    strip_redundant_parens,
)


def normalize_column_default(value: Optional[str]) -> Optional[str]:
    """Normalize a column default value for cross-dialect comparison.

    Accepts the raw value emitted by either a parsed CREATE script or a
    native introspection call and returns a canonical form so equivalent
    defaults compare equal across dialects (PostgreSQL casts, MySQL
    binary literals, SQL Server sequence references, DB2 ``CURRENT``
    aliases, ...).
    """
    if value is None:
        return None

    # Convert to string if not already (handles cases where value might be an int or other type)
    if not isinstance(value, str):
        value = str(value)

    # Remove surrounding whitespace first
    normalized = value.strip()

    # Remove redundant outer parentheses: ((value)) -> value
    while normalized.startswith("(") and normalized.endswith(")"):
        inner = normalized[1:-1].strip()
        if not inner:
            break
        normalized = inner

    # Handle PostgreSQL literal casts: 'value'::type or "value"::type
    cast_match = re.match(
        r"""^(?P<literal>(?:[Ee]?'[^']*'|"[^"]*"))\s*::[\w\s\."']+$""",
        normalized,
    )
    if cast_match:
        normalized = cast_match.group("literal")

    # Handle MySQL binary literal notation: b'1' or b'0'
    if normalized.startswith(("b'", "B'")) and normalized.endswith("'"):
        # Extract the binary value (0 or 1)
        binary_value = normalized[2:-1]
        # Convert binary literal to boolean equivalent
        if binary_value == "1":
            return "TRUE"
        elif binary_value == "0":
            return "FALSE"
        # For other binary values, keep as-is but remove the b'...' wrapper
        normalized = binary_value

    # Remove surrounding quotes (including E'...' escape form)
    if normalized.startswith(("E'", "e'")) and normalized.endswith("'"):
        normalized = normalized[2:-1]
    else:
        normalized = normalized.strip().strip("'").strip('"')

    # Remove trailing PostgreSQL cast that may remain (e.g., VALUE::INTEGER)
    normalized = re.sub(r"::[\w\s\.\"]+$", "", normalized)

    # Convert common variations
    if normalized.upper() in ["NULL", "NONE", ""]:
        return None

    # Normalize boolean values
    if normalized.upper() in ["TRUE", "T", "1", "YES", "Y"]:
        return "TRUE"
    if normalized.upper() in ["FALSE", "F", "0", "NO", "N"]:
        return "FALSE"

    # SQL Server specific normalization
    # Remove outer parentheses: (getdate()) -> getdate()
    if normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()

    # SQL Server sequence defaults: NEXT VALUE FOR [schema].[sequence]
    seq_match = re.match(r"NEXT\s+VALUE\s+FOR\s+(.+)", normalized, re.IGNORECASE)
    if seq_match:
        target = seq_match.group(1).strip().rstrip(";")
        target_clean = target.replace("[", "").replace("]", "").replace("`", "").replace('"', "")
        target_clean = re.sub(r"\s+", "", target_clean)
        return f"NEXT VALUE FOR {target_clean.upper()}"

    # DB2 specific: Normalize CURRENT TIMESTAMP, CURRENT DATE, etc.
    # DB2 allows both "CURRENT" and "CURRENT TIMESTAMP" as synonyms
    normalized_upper = normalized.upper()
    if normalized_upper in ("CURRENT TIMESTAMP", "CURRENT_TIMESTAMP"):
        return "CURRENT_TIMESTAMP"
    elif normalized_upper in ("CURRENT DATE", "CURRENT_DATE"):
        return "CURRENT_DATE"
    elif normalized_upper in ("CURRENT TIME", "CURRENT_TIME"):
        return "CURRENT_TIME"
    elif normalized_upper == "CURRENT":
        # DB2: "CURRENT" alone is a synonym for "CURRENT TIMESTAMP"
        return "CURRENT_TIMESTAMP"

    # Normalize function names to uppercase for consistency
    # This handles: getdate() -> GETDATE(), suser_name() -> SUSER_NAME()
    func_pattern = r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*(\(.*\))$"
    func_match = re.match(func_pattern, normalized)
    if func_match:
        func_name = func_match.group(1).upper()
        func_args = func_match.group(2)

        # For timestamp/datetime functions with empty parentheses, remove them
        # MySQL accepts CURRENT_TIMESTAMP and CURRENT_TIMESTAMP() as equivalent
        if (
            func_name
            in (
                "CURRENT_TIMESTAMP",
                "CURRENT_DATE",
                "CURRENT_TIME",
                "LOCALTIMESTAMP",
                "LOCALTIME",
                "NOW",
            )
            and func_args == "()"
        ):
            normalized = func_name
        else:
            normalized = f"{func_name}{func_args}"
    # Normalize PostgreSQL regclass casts inside expressions (nextval('seq'::regclass) -> nextval('seq'))
    normalized = re.sub(r"::\s*\"?regclass\"?\b", "", normalized, flags=re.IGNORECASE)

    return normalized


def normalize_check_expression(expr: Optional[str]) -> Optional[str]:
    """Normalize a CHECK expression for cross-dialect comparison.

    Removes the optional ``CHECK`` keyword, MySQL backticks and charset
    introducers, Oracle quoted identifiers, PostgreSQL ``::TYPE`` casts,
    redundant parentheses and boolean wrappers, then collapses whitespace
    so equivalent expressions compare equal regardless of the source
    formatting.
    """
    if expr is None:
        return None

    # Convert to string if not already (handles cases where check_expression might be an int)
    if not isinstance(expr, str):
        expr = str(expr)

    # Remove extra whitespace and normalize case
    normalized = " ".join(expr.split()).upper()

    # Remove "CHECK" keyword if present (case-insensitive)
    # Migration scripts may have "CHECK (expression)" while introspection returns just "expression"
    if normalized.startswith("CHECK"):
        normalized = normalized[5:].strip()
        # Remove leading/trailing whitespace after removing CHECK
        normalized = normalized.strip()

    # MySQL-specific: remove character set introducers (e.g., _utf8mb4'@')
    normalized = re.sub(r"_UTF8MB4'([^']*)'", r"'\1'", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"_UTF8'([^']*)'", r"'\1'", normalized, flags=re.IGNORECASE)

    # Remove MySQL backtick quoting before further normalization
    normalized = normalized.replace("`", "")

    # Remove outer parentheses if present (after removing CHECK keyword)
    # This handles cases like "(PRICE >= 0)" or "CHECK (PRICE >= 0)" -> "PRICE >= 0"
    if normalized.startswith("(") and normalized.endswith(")"):
        # Check if it's a balanced single set of outer parentheses
        # by counting parentheses (simple heuristic)
        paren_count = normalized.count("(")
        if paren_count == normalized.count(")") and paren_count > 0:
            # Try to determine if outer parentheses are just wrapping
            inner = normalized[1:-1].strip()
            # If inner has fewer or equal parentheses, likely just wrapping
            if inner.count("(") <= inner.count(")"):
                normalized = inner

    # Oracle-specific: Remove quotes from identifiers in expressions
    # Oracle returns: "PRICE"*"QUANTITY" but migration has: price * quantity
    # We remove quotes to normalize: PRICE*QUANTITY
    # But preserve quotes in string literals (e.g., 'text')
    # Pattern: Match quoted identifiers (double quotes) but not string literals (single quotes)
    normalized = re.sub(r'"([^"]+)"', r"\1", normalized)

    # MySQL-specific: remove backticks and character set introducers (e.g., _utf8mb4'@')
    normalized = normalized.replace("`", "")
    normalized = re.sub(r"_UTF8MB4'", "'", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"_UTF8MB4\\'([^']*)\\'", r"'\1'", normalized, flags=re.IGNORECASE)

    # Normalize whitespace around operators (*, +, -, /, =, etc.)
    # Handle compound operators first (>=, <=, <>, !=, ==) to avoid splitting them
    # Strategy: Replace compound operators with placeholders, process single operators, then restore
    compound_operators = [">=", "<=", "<>", "!=", "=="]
    compound_replacements = {}
    for i, op in enumerate(compound_operators):
        placeholder = f"__COMPOUND_OP_{i}__"
        normalized = normalized.replace(op, placeholder)
        compound_replacements[placeholder] = op

    # Now process single operators (won't match compound operators since they're replaced)
    normalized = re.sub(r"\s*([*/+\-=<>])\s*", r" \1 ", normalized)

    # Restore compound operators
    for placeholder, op in compound_replacements.items():
        normalized = normalized.replace(placeholder, op)

    normalized = " ".join(normalized.split())  # Normalize multiple spaces

    # Remove PostgreSQL style type casts (::TEXT, ::JSONB, etc.) for comparison
    normalized = re.sub(r"::[A-Z0-9_]+", "", normalized)

    # Ensure comma spacing is normalized
    normalized = re.sub(r",\s*", ", ", normalized)

    normalized = strip_boolean_wrappers(normalized)

    normalized = strip_redundant_parens(normalized)

    return normalized
