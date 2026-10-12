"""Narrow SQL execution statement splitting boundary."""

from __future__ import annotations

import logging as _logging
from typing import List, Optional, Union

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.logger import Log
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.parser_interface import SqlParserInterface


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
        self.parser_factory = SqlParserFactory(self.dialect, parser_type="regex")
        self._parser: Optional[SqlParserInterface] = None

    def split_statements(self, sql: str, *, strict_tokenizer: bool = False) -> List[str]:
        """Return executable units or refuse; never guess a second split."""
        if self._parser is None:
            self._parser = self.parser_factory.get_parser()
        try:
            return list(self._parser.split_statements(sql, strict_tokenizer=strict_tokenizer))
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError):
            raise
        except Exception as exc:
            raise UnsafeStatementSplitError(
                f"{self.dialect} statement splitter failed: {exc}"
            ) from exc
