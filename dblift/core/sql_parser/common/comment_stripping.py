"""Quote-aware comment stripping shared by every dialect's object extraction.

Extracted from ``EnhancedRegexParser._strip_comments_preserving_quotes`` so a
dialect that does not go through that base class (Oracle's regex parser,
which needs its own splitting and object model) can strip comments the same
way instead of re-deciding string/comment boundaries on its own.
"""

from __future__ import annotations

import re
from typing import List, Optional


def strip_comments_preserving_quotes(
    sql: str,
    *,
    line_prefixes: List[str],
    has_block_comments: bool,
    nested_block_comments: bool,
    supports_dollar_quoting: bool = False,
) -> str:
    """Remove comments without touching text inside a quoted span.

    A comment marker inside a single-quoted string, a double-quoted /
    backtick / bracket-quoted identifier, or (when ``supports_dollar_quoting``)
    a dollar-quoted body is not a comment and must be left alone. Doubled
    quote characters (``''``, ``""``, `` `` ``, ``]]``) are the escape form
    for a literal quote inside the span and do not end it. Block comments
    nest (``/* outer /* inner */ outer */``) only when
    ``nested_block_comments`` is true; otherwise the first ``*/`` closes,
    matching statement splitting for the same dialect.
    """
    markers = list(line_prefixes) + (["/*"] if has_block_comments else [])
    if not any(marker in sql for marker in markers):
        return sql.strip()

    result: List[str] = []

    in_single = False
    in_double = False
    in_backtick = False
    in_bracket = False
    block_comment_depth = 0
    in_line_comment = False
    dollar_tag: Optional[str] = None

    i = 0
    length = len(sql)
    while i < length:
        char = sql[i]

        if in_line_comment:
            if char in ("\n", "\r"):
                in_line_comment = False
                result.append(char)
            i += 1
            continue

        if block_comment_depth > 0:
            if nested_block_comments and char == "/" and sql[i + 1 : i + 2] == "*":
                block_comment_depth += 1
                i += 2
            elif char == "*" and sql[i + 1 : i + 2] == "/":
                block_comment_depth -= 1
                i += 2
            else:
                i += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                result.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
            else:
                result.append(char)
                i += 1
            continue

        in_quote = in_single or in_double or in_backtick or in_bracket

        if not in_quote and supports_dollar_quoting and char == "$":
            dollar_match = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", sql[i:])
            if dollar_match:
                tag = dollar_match.group(0)
                dollar_tag = tag
                result.append(tag)
                i += len(tag)
                continue

        if not in_double and not in_backtick and not in_bracket and char == "'":
            result.append(char)
            i += 1
            if in_single and sql[i : i + 1] == "'":
                result.append("'")
                i += 1
            else:
                in_single = not in_single
            continue

        if not in_single and not in_backtick and not in_bracket and char == '"':
            result.append(char)
            i += 1
            if in_double and sql[i : i + 1] == '"':
                result.append('"')
                i += 1
            else:
                in_double = not in_double
            continue

        if not in_single and not in_double and not in_bracket and char == "`":
            result.append(char)
            i += 1
            if in_backtick and sql[i : i + 1] == "`":
                result.append("`")
                i += 1
            else:
                in_backtick = not in_backtick
            continue

        if not in_single and not in_double and not in_backtick:
            if not in_bracket and char == "[":
                in_bracket = True
                result.append(char)
                i += 1
                continue
            if in_bracket and char == "]":
                result.append(char)
                i += 1
                if sql[i : i + 1] == "]":
                    result.append("]")
                    i += 1
                else:
                    in_bracket = False
                continue

        if not in_quote:
            if has_block_comments and char == "/" and sql[i + 1 : i + 2] == "*":
                block_comment_depth = 1
                i += 2
                continue
            matched_prefix = next((p for p in line_prefixes if sql.startswith(p, i)), None)
            if matched_prefix:
                in_line_comment = True
                i += len(matched_prefix)
                continue

        result.append(char)
        i += 1

    return "".join(result).strip()
