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
    if (
        ups[at : at + 1] != ["AS"]
        or at + 1 >= len(words)
        or not helpers._is_symbol(words[at + 1], "(")
    ):
        return None
    body_end = helpers._skip_group(words, at + 1)
    if body_end <= at + 2:
        return None
    body_words = words[at + 2 : body_end - 1]
    body_ups = ups[at + 2 : body_end - 1]
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
    inner_words = body_words[6 : data_end - 1]
    inner_ups = body_ups[6 : data_end - 1]
    if not inner_ups or inner_ups[0] != "UPDATE":
        return None
    if any(word in ("FROM", "JOIN") for word in inner_ups):
        return None
    write = helpers._read_dml(sql, inner_words, inner_ups, "UPDATE")
    if write.opaque or not write.target or not write.objects:
        return None
    outer = words[body_end:]
    outer_ups = ups[body_end:]
    if (
        len(outer) != 4
        or outer_ups[:1] != ["SELECT"]
        or outer_ups[2:3] != ["FROM"]
        or helpers.fold_name(outer[3].text) != cte_name[0]
        or helpers.fold_name(outer[1].text) != changed_column
    ):
        return None
    effect = DmlEffect(
        write.operation,
        write.target,
        write.target_sql or "",
        write.predicate,
        write.events or frozenset(),
        write.affected_columns,
    )
    return StatementFacts("SELECT", "DML", write.objects, cte_writes=(effect,))


def holds_data_change(ups: List[str]) -> bool:
    """Whether words contain a Db2 data-change table-reference phrase."""
    return any(a in ("FINAL", "NEW", "OLD") and b == "TABLE" for a, b in zip(ups, ups[1:]))
