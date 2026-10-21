"""Snowflake SQLGlot analysis with shared lexical statement boundaries."""

from typing import List

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.statement import Statement, execution_strings
from dblift.db.plugins.snowflake.lexical_spec import SNOWFLAKE_SPEC


class SnowflakeLexicalParser(SqlGlotParser):
    """Keep SQLGlot analysis while the plugin's lexical spec selects its SQL units."""

    def __init__(self) -> None:
        """Bind SQLGlot analysis to the Snowflake dialect."""
        super().__init__("snowflake")

    def split(self, sql_content: str) -> List[Statement]:
        """Return the Snowflake lexical engine's source-positioned records."""
        return LexicalEngine(SNOWFLAKE_SPEC).split(sql_content)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Project executable SQL strings from the lexical records."""
        return execution_strings(self.split(sql_content))
