"""In-process checks of the once-per-process legacy parser notice.

The subprocess tests in ``test_v5_alpha_deprecation`` prove the fresh-process
contract but are invisible to coverage; these run the same notice in the test
process, with the once-per-process memory reset around each test.
"""

from __future__ import annotations

import warnings

import pytest

from dblift.core.sql_parser import _deprecation
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from tests.support.legacy_snowflake_parsers import snowflake_facts_off


@pytest.fixture(autouse=True)
def fresh_notice_memory(monkeypatch):
    monkeypatch.setattr(_deprecation, "_warned", set())


def test_error_filter_raises_on_every_attempt_and_does_not_consume_the_notice() -> None:
    with snowflake_facts_off(), warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for _ in range(2):
            with pytest.raises(DeprecationWarning, match="HybridParser is deprecated"):
                HybridParser("snowflake")

    with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        HybridParser("snowflake")
        HybridParser("snowflake")
    assert len([w for w in seen if w.category is DeprecationWarning]) == 1


def test_notice_names_the_replacements_and_is_attributed_to_the_caller() -> None:
    with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        SqlGlotParser("snowflake")
        SqlGlotParser("snowflake")

    notices = [w for w in seen if w.category is DeprecationWarning]
    assert len(notices) == 1
    message = str(notices[0].message)
    assert message.startswith("SqlGlotParser is deprecated")
    assert "StatementSplitter" in message
    assert "StatementFactsParser" in message
    assert "introspection" in message
    assert notices[0].filename == __file__


def test_internal_bridge_stays_silent_and_leaves_the_notice_unconsumed() -> None:
    with snowflake_facts_off(), warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with _deprecation.internal_parser_construction():
            HybridParser("snowflake")
            SqlGlotParser("snowflake")

    with snowflake_facts_off(), warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        HybridParser("snowflake")
    assert len([w for w in seen if w.category is DeprecationWarning]) == 1


@pytest.mark.parametrize("name", ["RegexBasedParser", "RegexParser", "EnhancedRegexParser"])
def test_regex_roots_name_themselves_once_and_stay_silent_through_the_factory(name: str) -> None:
    from dblift.core.sql_parser.common.base_parser import RegexBasedParser
    from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
    from dblift.core.sql_parser.parser_factory import SqlParserFactory
    from dblift.core.sql_parser.unified_regex_parser import RegexParser
    from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig

    construct = {
        "RegexBasedParser": lambda: RegexBasedParser("oracle"),
        "RegexParser": lambda: RegexParser(MySqlConfig()),
        "EnhancedRegexParser": lambda: EnhancedRegexParser(MySqlConfig()),
    }[name]

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for dialect in ("oracle", "mysql", "postgresql"):
            with _deprecation.internal_parser_construction():
                factory = SqlParserFactory(dialect)
            factory.get_parser()

    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always", DeprecationWarning)
        construct()
        construct()
    notices = [w for w in seen if w.category is DeprecationWarning]
    assert len(notices) == 1
    assert str(notices[0].message).startswith(f"{name} is deprecated")
    assert "StatementSplitter" in str(notices[0].message)
