"""The unit a statement splitter hands to execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

StatementKind = Literal["sql", "directive", "copy_stdin"]


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
