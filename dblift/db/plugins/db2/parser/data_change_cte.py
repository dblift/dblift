"""Bounded facts for Db2 data-changing table references inside CTEs."""

from __future__ import annotations

from types import ModuleType
from typing import FrozenSet, List, Optional, Protocol, Tuple, cast

from dblift.core.sql_parser.statement_facts import DmlEffect, StatementFacts
from dblift.core.sql_parser.tokens import Token


class _ReaderHelpers(Protocol):
    _QUERY_RESERVED: FrozenSet[str]

    def _is_symbol(self, token: Token, text: str) -> bool:
        pass

    def _read_dml(self, sql: str, words: List[Token], ups: List[str], first: str) -> StatementFacts:
        pass

    def _read_name(
        self, words: List[Token], at: int, max_parts: int, stop: FrozenSet[str]
    ) -> Optional[Tuple[Tuple[str, ...], int, int, Tuple[bool, ...]]]:
        pass

    def _skip_group(self, words: List[Token], at: int) -> int:
        pass

    def fold_name(self, token_text: str) -> str:
        pass


def read_data_change_cte(
    sql: str, words: List[Token], ups: List[str], reader: ModuleType
) -> Optional[StatementFacts]:
    """Read one flat CTE whose SELECT reads a direct Db2 UPDATE table reference."""
    helpers = cast(_ReaderHelpers, reader)
    if not ups or ups[0] != "WITH":
        return None
    name = helpers._read_name(words, 1, 1, helpers._QUERY_RESERVED)
    if name is None:
        return None
    cte_name, _, at, _ = name
    declared = _read_declared_column(words, at, helpers)
    if declared is None:
        return None
    declared_column, at = declared
    body_end = _read_body_end(words, ups, at, helpers)
    if body_end is None:
        return None
    body_words = words[at + 2 : body_end - 1]
    body_ups = ups[at + 2 : body_end - 1]
    read = _read_final_table_update(sql, body_words, body_ups, declared_column, helpers)
    if read is None:
        return None
    changed_column, write = read
    if not _outer_select_reads(words[body_end:], ups[body_end:], cte_name, changed_column, helpers):
        return None
    effect = DmlEffect(
        write.operation,
        # _read_inner_update returns only a write with a target
        cast(str, write.target),
        write.target_sql or "",
        write.predicate,
        write.events or frozenset(),
        write.affected_columns,
    )
    return StatementFacts("SELECT", "DML", write.objects, cte_writes=(effect,))


def _read_declared_column(
    words: List[Token], at: int, helpers: _ReaderHelpers
) -> Optional[Tuple[Optional[str], int]]:
    """The one declared column after the CTE name (or ``None``) and the index after it.

    Returns ``None`` when a column list is present but is not exactly one plain name.
    """
    declared_column = None
    if at < len(words) and helpers._is_symbol(words[at], "("):
        columns_end = helpers._skip_group(words, at)
        if columns_end != at + 3 or not helpers._is_symbol(words[at + 2], ")"):
            return None
        column = helpers._read_name(words, at + 1, 1, helpers._QUERY_RESERVED)
        if column is None or column[2] != at + 2:
            return None
        declared_column = column[0][0]
        at = columns_end
    return declared_column, at


def _read_body_end(
    words: List[Token], ups: List[str], at: int, helpers: _ReaderHelpers
) -> Optional[int]:
    """The index after the parenthesised ``AS ( ... )`` body at ``at``, or ``None``."""
    if (
        ups[at : at + 1] != ["AS"]
        or at + 1 >= len(words)
        or not helpers._is_symbol(words[at + 1], "(")
    ):
        return None
    body_end = helpers._skip_group(words, at + 1)
    if body_end <= at + 2:
        return None
    return body_end


def _read_final_table_update(
    sql: str,
    body_words: List[Token],
    body_ups: List[str],
    declared_column: Optional[str],
    helpers: _ReaderHelpers,
) -> Optional[Tuple[str, StatementFacts]]:
    """The selected column and the inner UPDATE of ``SELECT col FROM FINAL TABLE (UPDATE ...)``.

    Returns ``None`` for any other body shape, a column other than the declared one, or an
    inner UPDATE that is not read.
    """
    # This bounded shape reads only the DML target; any other source remains opaque.
    if (
        len(body_words) < 7
        or body_ups[:1] != ["SELECT"]
        or body_ups[2:5] != ["FROM", "FINAL", "TABLE"]
        or not helpers._is_symbol(body_words[5], "(")
        or body_ups[1] in ("", "DISTINCT", "ALL")
    ):
        return None
    changed_column = helpers.fold_name(body_words[1].text)
    if declared_column is not None and changed_column != declared_column:
        return None
    data_end = helpers._skip_group(body_words, 5)
    if data_end != len(body_words):
        return None
    write = _read_inner_update(
        sql, body_words[6 : data_end - 1], body_ups[6 : data_end - 1], helpers
    )
    if write is None:
        return None
    return changed_column, write


def _read_inner_update(
    sql: str, inner_words: List[Token], inner_ups: List[str], helpers: _ReaderHelpers
) -> Optional[StatementFacts]:
    """The facts of a single-table UPDATE with a readable target, or ``None``."""
    if not inner_ups or inner_ups[0] != "UPDATE":
        return None
    if any(word in ("FROM", "JOIN") for word in inner_ups):
        return None
    write = helpers._read_dml(sql, inner_words, inner_ups, "UPDATE")
    if write.opaque or not write.target or not write.objects:
        return None
    return write


def _outer_select_reads(
    outer: List[Token],
    outer_ups: List[str],
    cte_name: Tuple[str, ...],
    changed_column: str,
    helpers: _ReaderHelpers,
) -> bool:
    """Whether the outer query is exactly ``SELECT <changed column> FROM <cte name>``."""
    if (
        len(outer) != 4
        or outer_ups[:1] != ["SELECT"]
        or outer_ups[2:3] != ["FROM"]
        or helpers.fold_name(outer[3].text) != cte_name[0]
        or helpers.fold_name(outer[1].text) != changed_column
    ):
        return False
    return True


def holds_data_change(ups: List[str]) -> bool:
    """Whether words contain a Db2 data-change table-reference phrase."""
    return any(a in ("FINAL", "NEW", "OLD") and b == "TABLE" for a, b in zip(ups, ups[1:]))
