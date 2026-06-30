"""Narrow SQL execution statement splitting boundary."""

from __future__ import annotations

import inspect
import logging as _logging
from typing import Callable, List, Optional, Union

from core.logger import Log
from core.sql_parser.parser_factory import SqlParserFactory
from core.sql_parser.parser_interface import SqlParserInterface

FallbackSplitter = Callable[[str], List[str]]


class StatementSplitter:
    """Split migration scripts without constructing rich schema-analysis parsers."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Union[Log, _logging.Logger]] = None,
    ):
        """Pick a regex parser for the given ``dialect`` — lighter than full schema parsing."""
        self.dialect = dialect.lower()
        self.logger = logger
        self.parser_factory = SqlParserFactory(self.dialect, parser_type="regex")
        self._parser: Optional[SqlParserInterface] = None

    def split_statements(
        self,
        sql: str,
        *,
        strict_tokenizer: bool = False,
        fallback: Optional[FallbackSplitter] = None,
    ) -> List[str]:
        """Split SQL content into executable statement strings."""
        try:
            parser = self._parser
            if parser is None:
                parser = self.parser_factory.get_parser()
                self._parser = parser

            split_signature = inspect.signature(parser.split_statements)
            supports_strict = "strict_tokenizer" in split_signature.parameters
            if supports_strict:
                statements = parser.split_statements(sql, strict_tokenizer=strict_tokenizer)
            else:
                statements = parser.split_statements(sql)

            if statements:
                return list(statements)
            if self.logger:
                self.logger.warning(
                    f"{self.dialect}-specific statement splitter returned no statements"
                )
        except TypeError:
            if strict_tokenizer:
                raise
            if self.logger:
                self.logger.warning(
                    f"{self.dialect}-specific statement splitter did not accept strict mode"
                )
        except Exception as exc:
            if strict_tokenizer:
                raise
            if self.logger:
                self.logger.warning(f"{self.dialect}-specific statement splitter failed: {exc}")

        if fallback is None:
            return []
        return list(fallback(sql))
