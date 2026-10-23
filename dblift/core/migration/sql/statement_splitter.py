"""Narrow SQL execution statement splitting boundary."""

from __future__ import annotations

import logging as _logging
from typing import Callable, List, Optional, Tuple, TypeVar, Union

from dblift.core.exceptions import (
    UnsafeStatementSplitError,
    UnsupportedDialectError,
    UnsupportedMetaCommandError,
)
from dblift.core.logger import Log
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement, execution_strings
from dblift.db.provider_registry import ProviderRegistry

_T = TypeVar("_T")


class StatementSplitter:
    """Split migration scripts with the dialect's authoritative scanner."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Union[Log, _logging.Logger]] = None,
    ):
        """Bind the dialect's lexical spec; a dialect without one is refused when it splits."""
        self.dialect = dialect.lower()
        self.logger = logger
        spec = ProviderRegistry.get_quirks(self.dialect).lexical_spec()
        self._engine = LexicalEngine(spec) if spec is not None else None
        self._last: Optional[Tuple[str, List[Statement]]] = None

    def _refusing(self, split: Callable[[], _T]) -> _T:
        """Run *split*; a refusal passes through, any other failure becomes one."""
        try:
            return split()
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError):
            raise
        except Exception as exc:
            raise UnsafeStatementSplitError(
                f"{self.dialect} statement splitter failed: {exc}"
            ) from exc

    def split(self, sql: str) -> List[Statement]:
        """The records of *sql* as the dialect's scanner cuts them, or its refusal."""
        records = self._split(sql)
        self._last = (sql, records)
        return list(records)

    def last_split(self, sql: str) -> List[Statement]:
        """The records of the last ``split`` when it was of *sql*, else a fresh split.

        A caller that needs the records of a script it has just split reads them here instead
        of splitting, and so logging the scanner's notices, a second time.
        """
        last = self._last
        if last is not None and last[0] == sql:
            return list(last[1])
        return self.split(sql)

    def _split(self, sql: str) -> List[Statement]:
        engine = self._engine
        if engine is not None:
            return self._refusing(lambda: engine.split(sql))
        raise UnsupportedDialectError(
            f"{self.dialect} has no lexical spec: a dialect is split by its LexicalSpec only"
        )

    def split_statements(self, sql: str) -> List[str]:
        """Return executable units or refuse; never guess a second split."""
        return execution_strings(self.split(sql))
