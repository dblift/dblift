"""Explicit test-only access to Snowflake's former SQL-file parser builders.

The public Snowflake parser reads statement facts. These helpers keep tests of the older
hybrid and SQLGlot builders, for Snowflake itself, without changing the public parser
contract. ``snowflake_facts_off`` covers a whole legacy factory or method sequence.
"""

from contextlib import contextmanager
from typing import Iterator, List
from unittest.mock import patch

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.statement import Statement, execution_strings
from dblift.db.plugins.snowflake.lexical_parser import SnowflakeLexicalParser
from dblift.db.plugins.snowflake.lexical_spec import SNOWFLAKE_SPEC
from dblift.db.plugins.snowflake.quirks import SnowflakeQuirks


class LegacySnowflakeLexicalParser(SqlGlotParser):
    """SQLGlot analysis with the plugin's lexical statement boundaries, before statement facts."""

    def __init__(self) -> None:
        super().__init__("snowflake")

    def split(self, sql_content: str) -> List[Statement]:
        return LexicalEngine(SNOWFLAKE_SPEC).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        return execution_strings(self.split(sql_content))


@contextmanager
def snowflake_facts_off() -> Iterator[None]:
    original = SnowflakeQuirks.parser_class

    def parser_class(self, parser_type):
        chosen = original(self, parser_type)
        return LegacySnowflakeLexicalParser if chosen is SnowflakeLexicalParser else chosen

    with (
        patch.object(SnowflakeQuirks, "statement_facts_class", None),
        patch.object(SnowflakeQuirks, "parser_class", parser_class),
    ):
        yield


def legacy_snowflake_hybrid() -> HybridParser:
    with snowflake_facts_off():
        return HybridParser("snowflake")


def legacy_snowflake_sqlglot() -> SqlGlotParser:
    with snowflake_facts_off():
        return SqlGlotParser("snowflake")
