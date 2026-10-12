import pytest

from dblift.core.sql_parser.common.base_parser import RegexBasedParser
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.unified_regex_parser import RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig


@pytest.mark.parametrize(
    "parser",
    [RegexBasedParser("mysql"), RegexParser(MySqlConfig()), EnhancedRegexParser(MySqlConfig())],
)
def test_semantic_parser_bases_require_a_dialect_scanner(parser) -> None:
    with pytest.raises(NotImplementedError):
        parser.split_statements("SELECT 'a;b'; SELECT 2;")
