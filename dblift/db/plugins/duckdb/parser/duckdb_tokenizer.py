"""DuckDB block-comment nesting flag.

``DuckDBRegexParser.split_statements`` does its own character-by-character
scan rather than instantiating a tokenizer, so this class exists only to
give ``EnhancedRegexParser``'s shared comment stripper the same answer the
splitter already assumes: DuckDB nests ``/* ... */`` (PostgreSQL-compatible).
"""

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer


class DuckDBTokenizer(BaseTokenizer):
    """Declares DuckDB's block-comment nesting rule for comment stripping."""

    NESTED_BLOCK_COMMENTS = True
