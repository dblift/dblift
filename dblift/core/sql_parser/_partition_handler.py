"""Partition metadata handling for the hybrid SQL parser.

Extracted from hybrid_parser.py to reduce file size.
Contains functions for parsing and normalizing partition metadata from CREATE TABLE statements.
"""

import re
from typing import List, Optional, Tuple

from dblift.core.sql_model.partition import Partition
from dblift.core.sql_model.table import Table


def _normalize_identifier(identifier: Optional[str], preserve_case: bool) -> str:
    """Normalize a SQL identifier by stripping quotes and brackets."""
    if identifier is None:
        return ""

    trimmed = identifier.strip().strip('"').strip("`")
    if trimmed.startswith("[") and trimmed.endswith("]"):
        trimmed = trimmed[1:-1]

    if "." in trimmed:
        trimmed = trimmed.split(".")[-1]

    return trimmed if preserve_case else trimmed.upper()


def apply_partition_metadata(table: Table, sql_text: str) -> None:
    """Extract partition metadata from SQL text and apply it to the table."""
    pattern = re.compile(r"PARTITION\s+BY\s+([A-Z_]+)\s*\(", re.IGNORECASE)
    match = pattern.search(sql_text)
    if not match:
        table.partition_method = None
        table.partition_columns = None
        return
    method = match.group(1).upper()
    start_index = match.end()
    column_expr = extract_balanced_partition_expression(sql_text, start_index)
    columns = normalize_partition_columns(column_expr)

    table.partition_method = method
    table.partition_columns = columns or None

    block = _read_partition_block(sql_text, start_index)
    if block is None:
        return
    end_index, _ = block
    column_expr = sql_text[start_index:end_index].strip()
    remainder = sql_text[end_index + 1 :].lstrip()
    count = re.match(r"PARTITIONS\s+([0-9]+)(?=\s|[;(]|$)", remainder, re.IGNORECASE)
    if count:
        try:
            table.partition_count = int(count.group(1))
        except ValueError:  # Python limits conversion of excessively long integers.
            return
        remainder = remainder[count.end() :].lstrip()

    # Skip the subpartition strategy; only top-level partitions are modelled.
    subpartition = re.match(r"SUBPARTITION\s+BY\s+[^()]+\(", remainder, re.IGNORECASE)
    if subpartition:
        subblock = _read_partition_block(remainder, subpartition.end())
        if subblock is None:
            return
        remainder = remainder[subblock[0] + 1 :].lstrip()
        remainder = re.sub(
            r"^SUBPARTITIONS\s+[0-9]+\b", "", remainder, flags=re.IGNORECASE
        ).lstrip()

    if not remainder.startswith("("):
        return
    definitions = _read_partition_block(remainder, 1)
    if definitions is None:
        return
    partitions = []
    for definition in definitions[1]:
        partition = _read_partition_definition(table, definition, method, column_expr)
        if partition is None:
            return  # Do not publish a partial list for an unrecognised clause.
        partitions.append(partition)
    table.export_partitions = partitions


def _read_partition_block(sql: str, start: int) -> Optional[Tuple[int, List[str]]]:
    """Read through a closing parenthesis, splitting only top-level commas.

    ``start`` follows the opening parenthesis. Quoted strings/identifiers and
    comments are opaque so their commas and parentheses cannot split the list.
    """
    tokens = re.finditer(
        r"'(?:''|\\.|[^'\\])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`" r"|/\*.*?\*/|--[^\n]*|[(),\"'`]",
        sql[start:],
        re.DOTALL,
    )
    depth = 0
    items = []
    item_start = start
    for token in tokens:
        char = token.group()
        position = start + token.start()
        if char in ('"', "'", "`"):
            return None  # A quote not consumed as a token is unterminated.
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                items.append(sql[item_start:position].strip())
                return position, items
            depth -= 1
        elif char == "," and depth == 0:
            items.append(sql[item_start:position].strip())
            item_start = position + 1
    return None


def _read_partition_definition(
    table: Table, definition: str, method: str, expression: str
) -> Optional[Partition]:
    """Read a name and verbatim bound, leaving storage/subpartition options opaque."""
    match = re.match(
        r'PARTITION\s+("(?:""|[^"])+"|`(?:``|[^`])+`|[\w$#]+)(?=\s|$)',
        definition,
        re.IGNORECASE,
    )
    if match is None:
        return None
    name = match.group(1)
    if name[0] in ('"', "`"):
        name = name[1:-1].replace(name[0] * 2, name[0])
    remainder = definition[match.end() :].lstrip()
    description = None
    bound = re.match(r"VALUES\s+(?:(?:LESS\s+THAN|IN)\s*)?", remainder, re.IGNORECASE)
    if bound:
        start = bound.end()
        if remainder[start:].startswith("("):
            block = _read_partition_block(remainder, start + 1)
            if block is None:
                return None
            description = remainder[: block[0] + 1]
        elif re.match(r"MAXVALUE\b", remainder[start:], re.IGNORECASE):
            description = remainder[: start + len("MAXVALUE")]
        else:
            return None
    return Partition(
        name=name,
        table=table.name,
        partition_method=method,
        partition_expression=expression,
        partition_description=description,
        schema=table.schema,
        dialect=table.dialect,
    )


def normalize_partition_columns(expression: str) -> List[str]:
    """Normalize partition column expressions into a list of column names."""
    columns: List[str] = []
    for raw in expression.split(","):
        candidate = raw.strip()
        if not candidate:
            continue

        candidate = strip_function_wrappers(candidate)
        normalized = _normalize_identifier(candidate, preserve_case=False)
        if normalized:
            columns.append(normalized)
    return columns


def extract_balanced_partition_expression(sql_text: str, start_index: int) -> str:
    """Extract the balanced parenthesized expression starting at start_index."""
    depth = 1
    chars: List[str] = []
    i = start_index
    while i < len(sql_text) and depth > 0:
        char = sql_text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        chars.append(char)
        i += 1
    return "".join(chars).strip()


def strip_function_wrappers(expression: str) -> str:
    """Iteratively strip outer function wrappers from an expression."""
    candidate = expression.strip()
    changed = True
    while changed:
        candidate, changed = strip_outer_function(candidate)
    # If nested parentheses remain unmatched, strip trailing closing parens
    while candidate.endswith(")") and candidate.count("(") < candidate.count(")"):
        candidate = candidate[:-1]
    return candidate.strip()


def strip_outer_function(expression: str) -> Tuple[str, bool]:
    """Strip a single outer function wrapper. Returns (result, was_stripped)."""
    expr = expression.strip()
    if not expr.endswith(")"):
        return expr, False

    depth = 0
    open_index = None
    for idx, char in enumerate(expr):
        if char == "(":
            depth += 1
            if depth == 1:
                open_index = idx
        elif char == ")":
            depth -= 1
            if depth == 0 and idx == len(expr) - 1 and open_index is not None:
                func_name = expr[:open_index].strip()
                if func_name and func_name.replace("_", "").replace("-", "").isalnum():
                    inner = expr[open_index + 1 : idx].strip()
                    # If the function had multiple arguments, assume column is last argument
                    if "," in inner:
                        inner = inner.split(",")[-1].strip()
                    return inner, True
    return expr, False
