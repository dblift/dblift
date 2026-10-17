"""DuckDB object parser; scripts are cut by the shared lexical engine."""

from typing import List, Optional, Type

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.duckdb.parser.duckdb_tokenizer import DuckDBTokenizer
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.duckdb.parser.parser_config import DuckDBParserConfig


class DuckDBRegexParser(EnhancedRegexParser):
    """DuckDB-specific regex-based SQL parser."""

    #: Object extraction's comment stripper uses this nested-comment rule;
    #: statement boundaries come from the shared engine.
    tokenizer_class: Type[BaseTokenizer] = DuckDBTokenizer

    #: The rules the engine cuts scripts with. Deliberately not named ``lexical_spec``: object
    #: extraction blanks comments through the engine when a parser has that attribute.
    _splitter_spec: LexicalSpec = DUCKDB_SPEC

    def __init__(self, config: Optional[DuckDBParserConfig] = None):
        """Initialize the DuckDB regex parser."""
        duckdb_config = config or DuckDBParserConfig()
        self.config = duckdb_config  # type: ignore[assignment]
        super().__init__(self.config)

    def split(self, sql_content: str) -> List[Statement]:
        """The statements of a script as the engine receives them (see docs/sql-parsing)."""
        return LexicalEngine(self._splitter_spec).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements execution sends: the text of each ``split()`` record.

        The engine has no unknown characters, so ``strict_tokenizer`` changes nothing.
        """
        return LexicalEngine(self._splitter_spec).split_statements(sql_content)

    def split_for_analysis(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """The statements of a script for callers that read it statement by statement.

        Execution drops a segment of comments only; the readers of a script (linting, analysis)
        still see it, as they did before the engine.
        """
        return LexicalEngine(self._splitter_spec).split_for_analysis(sql_content)

    def split_for_extraction(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project extraction text from the engine, retaining comment-only segments."""
        return self.split_for_analysis(sql_content, strict_tokenizer)
