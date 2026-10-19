"""The unit a statement splitter hands to execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Literal, Optional, Tuple

StatementKind = Literal["sql", "directive", "copy_stdin"]
_RUNS = ("sql", "copy_stdin")


@dataclass(frozen=True)
class Statement:
    """One statement of a script, verbatim, without the terminator that ended it.

    ``terminator`` is what ended the statement (``";"``, the ``\\.`` line of a
    COPY data block) or ``None`` when the script ended it. ``kind`` tells
    execution what it holds: SQL, a client directive dropped and recorded, or a
    COPY header with its data. ``multi`` is reserved for psql's ``\\;``.
    ``repeat`` is how often execution sends the statement: 1, or the count of the
    ``GO n`` that ended a T-SQL batch (0 sends it never).
    """

    text: str
    line: int
    terminator: Optional[str]
    kind: StatementKind = "sql"
    multi: bool = False
    repeat: int = 1
    # The string execution sends for this record when it is not ``text``. None sends ``text``
    # (SQL and COPY) or nothing (a directive: only one with text to send is sent).
    execution_text: Optional[str] = field(default=None, compare=False)
    # Derived by the same dialect scan as ``text``. None means this execution
    # unit is one analysis statement; () deliberately contributes none.
    analysis_statements: Optional[Tuple[str, ...]] = field(default=None, compare=False)
    # Half-open offsets in the original script, including a consumed client
    # terminator such as GO. Optional for externally constructed records.
    source_start: Optional[int] = field(default=None, compare=False)
    source_end: Optional[int] = field(default=None, compare=False)


def executable_records(records: Iterable[Statement]) -> List[Statement]:
    """The records execution runs: SQL and COPY statements that are not skipped, in order."""
    return [r for r in records if r.kind in _RUNS and r.repeat > 0]


def execution_strings(records: Iterable[Statement]) -> List[str]:
    """What execution sends: each statement as many times as it repeats.

    A directive is sent only when its producer gave it text to send.
    """
    out: List[str] = []
    for record in records:
        if record.kind in _RUNS:
            sent = record.text if record.execution_text is None else record.execution_text
        elif record.kind == "directive" and record.execution_text is not None:
            sent = record.execution_text
        else:
            continue
        out.extend([sent] * record.repeat)
    return out


def execution_units(records: Iterable[Statement]) -> List[str]:
    """Each executable statement once, as the splitter cut it."""
    return [record.text for record in executable_records(records)]


def analysis_sql(records: Iterable[Statement]) -> List[str]:
    """Executed constituents, once per unit even when a client repeats it."""
    return [
        sql
        for record in executable_records(records)
        for sql in (
            record.analysis_statements if record.analysis_statements is not None else (record.text,)
        )
    ]
