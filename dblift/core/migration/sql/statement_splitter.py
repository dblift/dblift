"""Narrow SQL execution statement splitting boundary."""

from __future__ import annotations

import logging as _logging
from typing import Callable, List, Optional, Tuple, TypeVar, Union

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.logger import Log
from dblift.core.sql_parser._deprecation import internal_parser_construction, warn_direct_parser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.parser_interface import SqlParserInterface
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
        """Resolve the dialect parser when the first script is split."""
        self.dialect = dialect.lower()
        self.logger = logger
        spec = ProviderRegistry.get_quirks(self.dialect).lexical_spec()
        self._engine = LexicalEngine(spec) if spec is not None else None
        self.parser_factory = None
        if self._engine is None:
            with internal_parser_construction():
                self.parser_factory = SqlParserFactory(self.dialect, parser_type="regex")
        self._parser: Optional[SqlParserInterface] = None
        self._last: Optional[Tuple[str, bool, List[Statement]]] = None

    def _record_parser(self) -> SqlParserInterface:
        if self._parser is None:
            assert self.parser_factory is not None
            self._parser = self.parser_factory.get_parser()
        return self._parser

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

    def split(self, sql: str, *, strict_tokenizer: Optional[bool] = None) -> List[Statement]:
        """The records of *sql* as the dialect's scanner cuts them, or its refusal."""
        if strict_tokenizer is not None:
            warn_direct_parser("strict_tokenizer")
        strict = bool(strict_tokenizer)
        records = self._split(sql, strict)
        self._last = (sql, strict, records)
        return list(records)

    def last_split(self, sql: str, *, strict_tokenizer: Optional[bool] = None) -> List[Statement]:
        """The records of the last ``split`` when it was of *sql*, else a fresh split.

        A caller that needs the records of a script it has just split reads them here instead
        of splitting, and so logging the scanner's notices, a second time.
        """
        if strict_tokenizer is not None:
            warn_direct_parser("strict_tokenizer")
        strict = bool(strict_tokenizer)
        last = self._last
        if last is not None and last[0] == sql and last[1] == strict:
            return list(last[2])
        with internal_parser_construction():
            return self.split(sql, strict_tokenizer=strict)

    def _split(self, sql: str, strict_tokenizer: bool) -> List[Statement]:
        engine = self._engine
        if engine is not None:
            return self._refusing(lambda: engine.split(sql))
        parser = self._record_parser()
        split = getattr(parser, "split", None)
        if not callable(split):
            raise UnsafeStatementSplitError(
                f"{self.dialect} statement parser must return Statement records from split()"
            )
        raw_records = self._refusing(lambda: split(sql))
        if isinstance(raw_records, (str, bytes)):
            raise UnsafeStatementSplitError(
                f"{self.dialect} statement parser must return Statement records from split()"
            )
        records = self._refusing(lambda: list(raw_records))
        if not all(isinstance(record, Statement) for record in records):
            raise UnsafeStatementSplitError(
                f"{self.dialect} statement parser must return Statement records from split()"
            )
        return records

    def split_statements(self, sql: str, *, strict_tokenizer: Optional[bool] = None) -> List[str]:
        """Return executable units or refuse; never guess a second split."""
        if strict_tokenizer is not None:
            warn_direct_parser("strict_tokenizer")
        with internal_parser_construction():
            return execution_strings(self.split(sql, strict_tokenizer=bool(strict_tokenizer)))
