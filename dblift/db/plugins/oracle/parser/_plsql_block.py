"""Oracle PL/SQL block extraction (Phase-Oracle-06 — ADR-0012).

This module owns the PL/SQL state machine: the logic that extracts a
complete ``CREATE PROCEDURE|FUNCTION|PACKAGE|...`` block or an
anonymous ``DECLARE/BEGIN ... END;`` block from a mixed Oracle script,
tracking nested ``BEGIN``/``END``, ``CASE ... END`` expressions, string
literals and doubled-quote escapes, ``END IF/LOOP/CASE`` control-flow
exceptions, and the trailing ``/`` delimiter.

Also hosts ``extract_java_source_block`` for ``CREATE JAVA SOURCE``
blocks, which track curly-brace depth instead of ``BEGIN``/``END``.

All functions are pure module-level functions. The regexes used by
``parse_plsql_create_header`` and ``is_single_plsql_block`` are
compiled once at module load.

Public surface
--------------

  * :func:`extract_plsql_block` — the entry point called by
    :mod:`_statement_splitter` when it encounters a PL/SQL keyword.
  * :func:`extract_java_source_block` — ``CREATE JAVA SOURCE`` path.
  * :func:`is_single_plsql_block` — predicate: is the entire input a
    single PL/SQL block?
  * :func:`is_partial_plsql_fragment` — predicate: is ``stmt`` a
    fragment (``END``, bare ``BEGIN``, bare ``DECLARE``, ``/``, ``;``)?
  * Helpers (``parse_plsql_create_header``, ``scan_to_plsql_body_start``,
    ``handle_plsql_end_keyword``, ``is_line_start_slash``) are exported
    to keep the existing test surface stable but are not intended as
    the public contract — call ``extract_plsql_block`` instead.

ADR-0012 §Follow-ups closed
---------------------------

``handle_plsql_end_keyword`` previously mutated a local ``statement``
parameter that never propagated back to the caller: Python strings
are immutable, so every non-terminating END (``END IF`` / ``END LOOP``
/ ``END CASE``) advanced the scanner position correctly but dropped
the literal ``END`` from the emitted block text. The helper now
returns ``statement`` as the sixth tuple element and the caller
reassigns it. Additionally, when END is followed by a control-flow
keyword, both are consumed as a single unit so the main loop does
not re-scan the keyword — this fixes the secondary bug where
``END CASE ; END;`` caused the outer ``END;`` to be misclassified
as control flow (the main loop was double-counting ``case_depth``).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from dblift.db.plugins.oracle.parser._statement_splitter import word_at_position

__all__ = [
    "extract_java_source_block",
    "extract_plsql_block",
    "handle_plsql_end_keyword",
    "is_line_start_slash",
    "is_partial_plsql_fragment",
    "is_single_plsql_block",
    "parse_plsql_create_header",
    "scan_to_plsql_body_start",
]


# Shared regex fragments.
_RE_EDITIONABLE = r"(?:(?:NON)?EDITIONABLE\s+)?"
_RE_OBJ_NAME = r'(?:(?:"[^"]+"|[a-zA-Z0-9_$#]+)\.)?(?:"[^"]+"|[a-zA-Z0-9_$#]+)'
_RE_BLOCK_END = r"END\s*(?:[a-zA-Z0-9_$#]+)?\s*;?\s*/?$"

# Compiled patterns for parse_plsql_create_header.
_RE_PACKAGE_BODY_HEADER = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?" + _RE_EDITIONABLE + r"PACKAGE\s+BODY\b",
    re.IGNORECASE,
)
_RE_COMPOUND_TRIGGER_HEADER = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?"
    + _RE_EDITIONABLE
    + r"(?:TRIGGER\s+\S+\s+.*?)?COMPOUND\s+TRIGGER\b",
    re.IGNORECASE | re.DOTALL,
)
_RE_JAVA_SOURCE_HEADER = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:AND\s+(?:RESOLVE|COMPILE)\s+)?JAVA\s+SOURCE\b",
    re.IGNORECASE,
)
_RE_OTHER_CREATE_HEADER = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?"
    + _RE_EDITIONABLE
    + r"(?:PROCEDURE|FUNCTION|PACKAGE|TRIGGER|TYPE(?:\s+BODY)?)\b",
    re.IGNORECASE,
)
_RE_PACKAGE_IS_PACKAGE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?" + _RE_EDITIONABLE + r"PACKAGE\b",
    re.IGNORECASE,
)
_RE_PACKAGE_NAME = re.compile(
    r"PACKAGE(?:\s+BODY)?\s+((?:[a-zA-Z0-9_$#\"]+\.)?[a-zA-Z0-9_$#\"]+)",
    re.IGNORECASE,
)

# Compiled patterns for is_single_plsql_block.
_RE_SINGLE_PLSQL_PATTERNS: Tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.DOTALL | re.IGNORECASE)
    for p in (
        # Standalone trigger (regular and compound)
        rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{_RE_EDITIONABLE}"
        rf"(?:COMPOUND\s+)?TRIGGER\s+{_RE_OBJ_NAME}.*?{_RE_BLOCK_END}",
        # Standalone procedure
        rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{_RE_EDITIONABLE}"
        rf"PROCEDURE\s+{_RE_OBJ_NAME}.*?{_RE_BLOCK_END}",
        # Standalone function
        rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{_RE_EDITIONABLE}"
        rf"FUNCTION\s+{_RE_OBJ_NAME}.*?{_RE_BLOCK_END}",
        # Standalone package or package body
        rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{_RE_EDITIONABLE}"
        rf"PACKAGE(?:\s+BODY)?\s+{_RE_OBJ_NAME}.*?{_RE_BLOCK_END}",
        # Type or type body
        rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?{_RE_EDITIONABLE}"
        rf"TYPE(?:\s+BODY)?\s+{_RE_OBJ_NAME}.*?{_RE_BLOCK_END}",
        # Anonymous block
        r"^\s*(?:DECLARE\s+.*?)?BEGIN\s+.*?END\s*;?\s*/?$",
    )
)

# Fragment patterns for is_partial_plsql_fragment.
_FRAGMENT_PATTERNS: Tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^\s*END\s*;?\s*/?$",  # Just END
        r"^\s*BEGIN\s*$",  # Just BEGIN
        r"^\s*DECLARE\s*$",  # Just DECLARE
        r"^\s*/\s*$",  # Just slash
        r"^\s*;\s*$",  # Just semicolon
    )
)

# SQL keywords that commonly follow CASE END in expressions.
_CASE_END_SQL_KEYWORDS = frozenset(
    [
        "WHERE",
        "AND",
        "OR",
        "FROM",
        "ORDER",
        "GROUP",
        "HAVING",
        "UNION",
        "INTERSECT",
        "MINUS",
        "EXCEPT",
        "JOIN",
        "LEFT",
        "RIGHT",
        "INNER",
        "OUTER",
        "CROSS",
        "NATURAL",
        "ON",
        "AS",
        "INTO",
        "VALUES",
        "SET",
        "WHEN",
        "THEN",
        "ELSE",
        "IS",
        "NOT",
        "NULL",
        "LIKE",
        "IN",
        "BETWEEN",
        "EXISTS",
        "ALL",
        "ANY",
        "SOME",
        "FOR",
        "WITH",
        "LIMIT",
        "OFFSET",
        "FETCH",
        "RETURNING",
        "UPDATE",
        "DELETE",
        "INSERT",
        "SELECT",
    ]
)


def parse_plsql_create_header(
    text: str, i: int
) -> Tuple[bool, bool, bool, bool, Optional[str], str, int]:
    """Detect the type of CREATE block and extract header metadata.

    Returns:
        ``(is_named_block, is_package_body, is_package, is_compound_trigger,
        package_name, statement_prefix, new_i)``. ``statement_prefix`` is
        the sentinel ``"JAVA_SOURCE"`` when the caller must delegate to
        :func:`extract_java_source_block`, and ``""`` otherwise.
    """
    remaining = text[i:].strip()

    is_package_body_match = _RE_PACKAGE_BODY_HEADER.match(remaining)
    is_compound_trigger_match = _RE_COMPOUND_TRIGGER_HEADER.match(remaining)
    is_java_source_match = _RE_JAVA_SOURCE_HEADER.match(remaining)
    is_other_block_match = _RE_OTHER_CREATE_HEADER.match(remaining)

    if is_java_source_match:
        return False, False, False, False, None, "JAVA_SOURCE", i

    if not (is_package_body_match or is_compound_trigger_match or is_other_block_match):
        return False, False, False, False, None, "", i

    is_named_block = True
    is_compound_trigger = bool(is_compound_trigger_match)
    is_package_body = bool(is_package_body_match) or is_compound_trigger
    is_package = bool(not is_package_body and _RE_PACKAGE_IS_PACKAGE.search(remaining))

    package_name: Optional[str] = None
    if is_package_body or is_package:
        name_match = _RE_PACKAGE_NAME.search(remaining)
        if name_match:
            full_name = name_match.group(1)
            if "." in full_name:
                package_name = full_name.split(".")[-1].strip('"').upper()
            else:
                package_name = full_name.strip('"').upper()

    return is_named_block, is_package_body, is_package, is_compound_trigger, package_name, "", i


def scan_to_plsql_body_start(
    text: str,
    i: int,
    statement: str,
    is_named_block: bool,
    is_package: bool,
    is_package_body: bool,
    is_compound_trigger: bool,
) -> Tuple[str, int, int]:
    """Scan from after the CREATE header to the AS/IS/BEGIN keyword.

    Returns:
        ``(statement_accumulated, position_at_body_start, block_depth)``.
    """
    in_string = False
    string_char: Optional[str] = None
    block_depth = 0

    while i < len(text):
        if not in_string:
            if is_compound_trigger and word_at_position(text, i, "COMPOUND"):
                statement += text[i : i + 8]  # "COMPOUND" = 8 chars
                i += 8
                while i < len(text) and text[i].isspace():
                    statement += text[i]
                    i += 1
                if word_at_position(text, i, "TRIGGER"):
                    statement += text[i : i + 7]
                    i += 7
                return statement, i, 1
            elif word_at_position(text, i, "AS") or word_at_position(text, i, "IS"):
                statement += text[i : i + 2]
                i += 2
                block_depth = 1 if (is_package or is_package_body) else 0
                break
            elif word_at_position(text, i, "BEGIN"):
                statement += text[i : i + 5]
                i += 5
                return statement, i, 1
            elif text[i] in ("'", '"'):
                in_string = True
                string_char = text[i]
        else:
            if text[i] == string_char:
                if i + 1 < len(text) and text[i + 1] == string_char:
                    statement += text[i : i + 2]
                    i += 2
                    continue
                in_string = False
                string_char = None
        statement += text[i]
        i += 1

    # Second pass: scan to BEGIN for procedures/functions with AS/IS.
    if block_depth == 0:
        in_string = False
        string_char = None
        while i < len(text):
            if not in_string:
                if word_at_position(text, i, "BEGIN"):
                    statement += text[i : i + 5]
                    i += 5
                    return statement, i, 1
                elif text[i] in ("'", '"'):
                    in_string = True
                    string_char = text[i]
            else:
                if text[i] == string_char:
                    if i + 1 < len(text) and text[i + 1] == string_char:
                        statement += text[i : i + 2]
                        i += 2
                        continue
                    in_string = False
                    string_char = None
            statement += text[i]
            i += 1

    return statement, i, block_depth


def handle_plsql_end_keyword(
    text: str,
    i: int,
    block_depth: int,
    case_depth: int,
    case_block_depth_stack: List[int],
    is_package_body: bool,
    package_name: Optional[str],
    statement: str,
    is_named_block: bool,
) -> Tuple[int, int, List[int], Optional[Tuple[str, int]], int, str]:
    """Handle the END keyword in the main BEGIN/END tracking loop.

    Returns:
        ``(new_block_depth, new_case_depth, new_case_stack,
        result_or_none, new_i, new_statement)``. ``result_or_none``
        is ``(statement, position)`` when the block terminates here,
        else ``None``. ``new_statement`` is always returned so the
        caller can reassign its own ``statement`` and pick up the
        ``END`` characters (plus any post-END identifier / ``;`` /
        ``/`` on the terminating path).
    """
    # ``is_package_body`` and ``package_name`` are accepted to preserve
    # the caller's signature; they are not consulted by the current
    # control-flow heuristics.
    del is_package_body, package_name

    is_control_flow_end = False

    # Chars past END to consume together with the END itself. Remains 0
    # unless END is followed by a control-flow keyword (IF/LOOP/CASE/
    # REPEAT). Hoisted above the ``if end_pos < len(text):`` guard so
    # the end-of-input path (END as the final token) does not reference
    # an unbound local.
    control_flow_keyword_end = 0

    end_pos = i + 3
    while end_pos < len(text) and text[end_pos].isspace():
        end_pos += 1

    char_after_end = text[end_pos] if end_pos < len(text) else None

    if end_pos < len(text):
        case_end_handled = False
        if case_depth > 0:
            if char_after_end in ("|", "+", "-", "*", "/", ",", ")"):
                case_depth -= 1
                if case_block_depth_stack:
                    case_block_depth_stack.pop()
                is_control_flow_end = True
                case_end_handled = True
            elif char_after_end in ("'", '"'):
                case_depth -= 1
                if case_block_depth_stack:
                    case_block_depth_stack.pop()
                is_control_flow_end = True
                case_end_handled = True
            elif char_after_end and char_after_end.isalpha():
                if word_at_position(text, end_pos, "IF"):
                    pass
                elif word_at_position(text, end_pos, "LOOP"):
                    pass
                elif word_at_position(text, end_pos, "CASE"):
                    pass
                elif any(word_at_position(text, end_pos, kw) for kw in _CASE_END_SQL_KEYWORDS):
                    case_depth -= 1
                    if case_block_depth_stack:
                        case_block_depth_stack.pop()
                    is_control_flow_end = True
                    case_end_handled = True

        # When END is followed by a control-flow keyword we consume the
        # keyword together with the END so the main loop does not
        # re-scan it. This is especially important for ``CASE``: the
        # main loop treats ``CASE`` as a case-block opener and would
        # otherwise increment ``case_depth`` a second time, later
        # misclassifying the outer terminating END as control flow.
        if (
            word_at_position(text, end_pos, "IF")
            or word_at_position(text, end_pos, "LOOP")
            or word_at_position(text, end_pos, "CASE")
            or word_at_position(text, end_pos, "REPEAT")
        ):
            if word_at_position(text, end_pos, "CASE") and case_depth > 0:
                case_depth -= 1
                if case_block_depth_stack:
                    case_block_depth_stack.pop()
            is_control_flow_end = True
            kw_len = next(
                len(kw)
                for kw in ("REPEAT", "LOOP", "CASE", "IF")
                if word_at_position(text, end_pos, kw)
            )
            control_flow_keyword_end = end_pos + kw_len
        elif not case_end_handled and char_after_end in ("|", "+", "-", "*", "/", ","):
            if case_depth > 0:
                case_depth -= 1
                if case_block_depth_stack:
                    case_block_depth_stack.pop()
            is_control_flow_end = True
        elif not case_end_handled and char_after_end == ";":
            if case_depth > 0 and case_block_depth_stack:
                case_start_block_depth = case_block_depth_stack[-1]
                if block_depth > case_start_block_depth:
                    is_control_flow_end = False
                else:
                    case_depth -= 1
                    case_block_depth_stack.pop()
                    is_control_flow_end = True
            elif is_named_block:
                if "TRIGGER" in statement.upper():
                    is_control_flow_end = False
                else:
                    temp_pos = end_pos + 1
                    while temp_pos < len(text) and text[temp_pos].isspace():
                        temp_pos += 1
                    if temp_pos < len(text) and text[temp_pos] == "/":
                        is_control_flow_end = False
                    elif block_depth > 1:
                        is_control_flow_end = False
                    else:
                        if temp_pos < len(text):
                            next_char = text[temp_pos]
                            if next_char in ("|", "+", "-", "*", "/", ","):
                                is_control_flow_end = True
                            elif word_at_position(text, temp_pos, "AND") or word_at_position(
                                text, temp_pos, "OR"
                            ):
                                is_control_flow_end = True
                            else:
                                is_control_flow_end = False
                        else:
                            is_control_flow_end = False
        elif end_pos < len(text) and (
            text[end_pos].isalnum() or text[end_pos] == "_" or text[end_pos] == '"'
        ):
            pass  # identifier after END (e.g. END my_proc) — not control flow

    if control_flow_keyword_end:
        statement += text[i:control_flow_keyword_end]
        i = control_flow_keyword_end
    else:
        statement += text[i : i + 3]
        i = i + 3

    if not is_control_flow_end:
        block_depth -= 1

        if block_depth <= 0:
            if i < len(text) and text[i].isspace():
                while i < len(text) and text[i].isspace():
                    statement += text[i]
                    i += 1

            if i < len(text) and text[i] == '"':
                statement += text[i]
                i += 1
                while i < len(text) and text[i] != '"':
                    statement += text[i]
                    i += 1
                if i < len(text):
                    statement += text[i]
                    i += 1
            else:
                while i < len(text) and (text[i].isalnum() or text[i] == "_" or text[i] == "."):
                    statement += text[i]
                    i += 1

            if i < len(text) and text[i] == ";":
                statement += text[i]
                i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            if i < len(text) and text[i] == "/":
                i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            return (
                block_depth,
                case_depth,
                case_block_depth_stack,
                (statement.strip(), i),
                i,
                statement,
            )

    return block_depth, case_depth, case_block_depth_stack, None, i, statement


def is_line_start_slash(text: str, pos: int) -> bool:
    """Return ``True`` if the ``/`` at ``pos`` is the first non-whitespace char on its line."""
    check = pos - 1
    while check >= 0:
        if text[check] == "\n":
            return True
        if not text[check].isspace():
            return False
        check -= 1
    return True  # Start of file.


def extract_java_source_block(text: str, start_pos: int) -> Tuple[str, int]:
    """Extract a ``CREATE JAVA SOURCE`` block by tracking curly-brace depth.

    Java source uses ``{}`` for block delimiters instead of
    ``BEGIN``/``END``. The block ends when the brace depth returns to
    zero, followed by an optional trailing ``/``.
    """
    i = start_pos
    statement = ""
    in_string = False
    string_char: Optional[str] = None
    brace_depth = 0
    found_as = False

    while i < len(text):
        char = text[i]

        if not in_string and char in ('"', "'"):
            in_string = True
            string_char = char
            statement += char
            i += 1
            continue
        elif in_string and char == string_char:
            if i + 1 < len(text) and text[i + 1] == string_char:
                statement += char + char
                i += 2
                continue
            in_string = False
            string_char = None
            statement += char
            i += 1
            continue
        elif in_string:
            statement += char
            i += 1
            continue

        if not found_as:
            if word_at_position(text, i, "AS"):
                statement += text[i : i + 2]
                i += 2
                found_as = True
            else:
                statement += char
                i += 1
            continue

        if char == "{":
            brace_depth += 1
            statement += char
            i += 1
            continue
        elif char == "}":
            brace_depth -= 1
            statement += char
            i += 1
            if brace_depth == 0:
                while i < len(text) and text[i].isspace():
                    i += 1
                if i < len(text) and text[i] == "/":
                    i += 1
                    while i < len(text) and text[i].isspace():
                        i += 1
                return statement.strip(), i
            continue

        statement += char
        i += 1

    return statement.strip(), len(text)


def extract_plsql_block(text: str, start_pos: int) -> Tuple[str, int]:
    """Extract a complete PL/SQL block (handles nested BEGIN/END).

    Entry point for :mod:`_statement_splitter`. Dispatches to
    :func:`extract_java_source_block` for ``CREATE JAVA SOURCE``.
    """
    i = start_pos
    block_depth = 0
    case_depth = 0
    case_block_depth_stack: List[int] = []
    in_string = False
    string_char: Optional[str] = None
    statement = ""
    is_named_block = False
    is_package_body = False
    is_package = False
    is_compound_trigger = False
    package_name: Optional[str] = None

    # Skip leading whitespace.
    while i < len(text) and text[i].isspace():
        statement += text[i]
        i += 1

    # Phase 2a: detect CREATE header type.
    if i < len(text):
        (
            is_named_block,
            is_package_body,
            is_package,
            is_compound_trigger,
            package_name,
            prefix,
            i,
        ) = parse_plsql_create_header(text, i)
        if prefix == "JAVA_SOURCE":
            return extract_java_source_block(text, start_pos)

    # Phase 2b: scan to AS/IS/BEGIN for named blocks.
    if is_named_block:
        statement, i, block_depth = scan_to_plsql_body_start(
            text,
            i,
            statement,
            is_named_block,
            is_package,
            is_package_body,
            is_compound_trigger,
        )

    # Phase 3: main BEGIN/END tracking loop.
    while i < len(text):
        char = text[i]

        if not in_string and char in ("'", '"'):
            in_string = True
            string_char = char
            statement += char
            i += 1
            continue
        elif in_string and char == string_char:
            if i + 1 < len(text) and text[i + 1] == string_char:
                statement += char + char
                i += 2
                continue
            in_string = False
            string_char = None
            statement += char
            i += 1
            continue
        elif in_string:
            statement += char
            i += 1
            continue

        if not in_string:
            if word_at_position(text, i, "CASE"):
                case_depth += 1
                case_block_depth_stack.append(block_depth)
                statement += text[i : i + 4]
                i += 4
                continue
            elif word_at_position(text, i, "BEGIN"):
                block_depth += 1
                statement += text[i : i + 5]
                i += 5
                continue
            elif word_at_position(text, i, "END"):
                (
                    block_depth,
                    case_depth,
                    case_block_depth_stack,
                    result,
                    i,
                    statement,
                ) = handle_plsql_end_keyword(
                    text,
                    i,
                    block_depth,
                    case_depth,
                    case_block_depth_stack,
                    is_package_body,
                    package_name,
                    statement,
                    is_named_block,
                )
                if result is not None:
                    return result
                continue

        # Package-body init section: force-terminate on a standalone line-start slash.
        if char == "/" and is_package_body and block_depth > 0:
            if is_line_start_slash(text, i):
                i += 1
                while i < len(text) and text[i].isspace():
                    i += 1
                return statement.strip(), i

        statement += char
        i += 1

    return statement.strip(), len(text)


def is_single_plsql_block(sql: str) -> bool:
    """Return ``True`` if the entire input is a single PL/SQL block."""
    sql_clean = sql.strip()
    return any(pattern.search(sql_clean) for pattern in _RE_SINGLE_PLSQL_PATTERNS)


def is_partial_plsql_fragment(stmt: str) -> bool:
    """Return ``True`` if ``stmt`` is a partial PL/SQL fragment."""
    stmt = stmt.strip()
    if not stmt:
        return True

    # Complete PL/SQL blocks are not fragments.
    if is_single_plsql_block(stmt):
        return False

    return any(pattern.search(stmt) for pattern in _FRAGMENT_PATTERNS)
