"""Oracle statement boundary detection (Phase-Oracle-05 — ADR-0012).

This module owns the hot path: splitting a multi-statement Oracle
script into individual statements. It is:

  * semicolon-aware for regular DDL/DML,
  * string-literal-aware (single and double quotes, Oracle-style
    ``''`` doubled-quote escape),
  * PL/SQL-aware via an injected ``extract_plsql_block`` callable
    (the PL/SQL state machine stays in ``oracle_parser.py`` until
    Phase-Oracle-06 extracts it to ``_plsql_block.py``; at that point
    the injection becomes a direct import and the call sites lose the
    keyword argument),
  * SQL*Plus-aware via :func:`_sqlplus.is_sqlplus_command`,
  * comment-aware via :func:`_comments.strip_sql_comments`.

All functions are pure module-level functions. PL/SQL block headers are
detected by :func:`_sqlplus.is_plsql_keyword_start`.
"""

from __future__ import annotations

import re
from typing import Callable, List, Tuple

from dblift.db.plugins.oracle.parser._comments import strip_sql_comments
from dblift.db.plugins.oracle.parser._sqlplus import (
    is_plsql_keyword_start,
    is_sqlplus_command,
    tokenize_outside_sqlplus_directives,
)
from dblift.db.plugins.oracle.parser.oracle_tokenizer import (
    OracleTokenizer,
    has_stray_comment_close,
)

__all__ = [
    "extract_next_complete_statement",
    "extract_regular_statement",
    "is_empty_or_comment",
    "is_plsql_keyword_start",
    "split_statements_regex",
    "word_at_position",
]


# Type alias for the PL/SQL block extractor callable injected by the
# parser. ``(text, start_pos) -> (block_text, next_pos)``. See the
# module docstring for why this is injected rather than imported.
PlsqlBlockExtractor = Callable[[str, int], Tuple[str, int]]


def word_at_position(text: str, pos: int, word: str) -> bool:
    """Return ``True`` iff ``word`` appears at ``pos`` as a whole word.

    Oracle identifier boundaries: a word edge is anything that is not a
    letter, digit, underscore, ``$`` or ``#``.
    """
    if pos + len(word) > len(text):
        return False

    if text[pos : pos + len(word)].upper() != word.upper():
        return False

    def _is_identifier_char(c: str) -> bool:
        return c.isalnum() or c in ("_", "$", "#")

    if pos > 0 and _is_identifier_char(text[pos - 1]):
        return False
    if pos + len(word) < len(text) and _is_identifier_char(text[pos + len(word)]):
        return False

    return True


def extract_regular_statement(text: str, start_pos: int) -> Tuple[str, int]:
    """Extract a regular SQL statement ending with ``;``.

    Respects string literals: single and double quotes, and the Oracle
    doubled-quote escape (``'O''Reilly'``). After the terminating
    semicolon, optional whitespace and an optional trailing ``/``
    delimiter (SQL*Plus) are consumed.
    """
    i = start_pos
    in_string = False
    string_char = None
    statement = ""
    line_buffering = False

    while i < len(text):
        char = text[i]

        if not in_string and char in ("'", '"'):
            in_string = True
            string_char = char
            statement += char
            i += 1
            continue
        elif in_string and char == string_char:
            # Doubled quote (``''``) — escaped quote inside the literal.
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

        if not in_string and char == ";":
            statement += char
            i += 1

            # A "*/" left on this line outside a literal is stray (comments
            # are already stripped). SQL*Plus does not end the statement
            # there, and from then on only at a ";" that is the last thing on
            # its line (see OracleStatementParser._ends_sqlplus_line).
            eol = text.find("\n", i)
            rest_of_line = text[i : eol if eol != -1 else len(text)]
            if not line_buffering and "*/" in rest_of_line:
                line_buffering = has_stray_comment_close(OracleTokenizer(rest_of_line).tokenize())
            if line_buffering and rest_of_line.strip():
                continue

            # Swallow whitespace and an optional trailing SQL*Plus ``/``.
            while i < len(text) and text[i].isspace():
                i += 1
            if i < len(text) and text[i] == "/":
                i += 1
                while i < len(text) and text[i].isspace():
                    i += 1

            return statement.strip(), i

        statement += char
        i += 1

    return statement.strip(), len(text)


def extract_next_complete_statement(
    text: str,
    start_pos: int,
    *,
    extract_plsql_block: PlsqlBlockExtractor,
) -> Tuple[str, int]:
    """Dispatch: PL/SQL block vs regular statement.

    The PL/SQL path is delegated to ``extract_plsql_block`` (injected
    by the parser until Phase-Oracle-06 extracts it).
    """
    if start_pos >= len(text):
        return "", start_pos

    remaining = text[start_pos:].strip()
    if not remaining:
        return "", len(text)

    if is_plsql_keyword_start(remaining):
        return extract_plsql_block(text, start_pos)
    return extract_regular_statement(text, start_pos)


def is_empty_or_comment(stmt: str) -> bool:
    """Return ``True`` if ``stmt`` is empty, only comments, or a SQL*Plus directive."""
    if not stmt or not stmt.strip():
        return True

    cleaned = re.sub(r"--.*$", "", stmt, flags=re.MULTILINE)
    cleaned = re.sub(r"/\*.*?\*/", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = cleaned.strip()

    if not cleaned or cleaned == ";":
        return True

    return is_sqlplus_command(cleaned)


def split_statements_regex(
    sql: str,
    *,
    extract_plsql_block: PlsqlBlockExtractor,
) -> List[str]:
    """Split a multi-statement Oracle script using the regex/block-aware path.

    Walks the input left-to-right, dispatching each statement to
    :func:`extract_next_complete_statement`. Empties, comment-only
    chunks, bare ``/`` or ``;``, and SQL*Plus directives are dropped.
    Leading/trailing ``/`` delimiters (SQL*Plus, not valid executable SQL)
    are stripped from the retained statements.
    """
    if not sql.strip():
        return []

    statements: List[str] = []
    # SQL*Plus directives end at the end of their line, with or without a
    # ";", and their text is not SQL: drop them so "PROMPT customer's table"
    # neither opens a literal nor merges with the next statement.
    _, directive_lines = tokenize_outside_sqlplus_directives(sql)
    parts, last = [], 0
    for start, end in directive_lines:
        parts.append(sql[last:start])
        last = end
    parts.append(sql[last:])
    text = strip_sql_comments("".join(parts)).strip()
    i = 0

    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break

        statement, next_pos = extract_next_complete_statement(
            text, i, extract_plsql_block=extract_plsql_block
        )

        if statement and not is_empty_or_comment(statement):
            stmt_clean = statement.strip()
            if stmt_clean.startswith("/"):
                stmt_clean = stmt_clean[1:].strip()
            if stmt_clean.endswith("/"):
                stmt_clean = stmt_clean[:-1].strip()
            if stmt_clean and stmt_clean not in ("/", ";") and not is_sqlplus_command(stmt_clean):
                statements.append(stmt_clean)

        i = next_pos

    return statements
