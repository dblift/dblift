"""Db2 data-change CTE reader: shapes the bounded reader declines."""

import pytest

from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.db2.parser import statement_facts as reader
from dblift.db.plugins.db2.parser.data_change_cte import read_data_change_cte
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.db2.parser.statement_facts import DATA_CHANGE_QUERY, Db2StatementFactsReader

pytestmark = [pytest.mark.unit]

READ = Db2StatementFactsReader(None).read
SUPPORTED_BODY = "c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c"


def _read_direct(sql):
    words = reader._words(LexicalTokenizer(sql, spec=DB2_SPEC).tokenize())
    ups = [t.text.upper() if t.type is TokenType.KEYWORD else "" for t in words]
    return read_data_change_cte(sql, words, ups, reader)


def test_direct_call_reads_the_supported_shape():
    facts = _read_direct("WITH " + SUPPORTED_BODY)

    assert facts is not None
    assert [(w.operation, w.target) for w in facts.cte_writes] == [("UPDATE", "T")]


def test_direct_call_declines_a_statement_that_does_not_start_with_with():
    assert _read_direct("SELECT " + SUPPORTED_BODY) is None


def test_direct_call_declines_an_empty_statement():
    assert read_data_change_cte("", [], [], reader) is None


@pytest.mark.parametrize(
    "sql",
    [
        # the CTE body is never closed
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1) SELECT id FROM c",
        # ALL is a quantifier, not the selected column
        "WITH c AS (SELECT ALL FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT ALL FROM c",
        # the outer query must be exactly SELECT <column> FROM <cte>
        "WITH c AS (SELECT id FROM FINAL TABLE (UPDATE t SET id = 1)) SELECT id FROM c WHERE 1 = 1",
    ],
)
def test_unread_data_change_cte_stays_opaque(sql):
    facts = READ(sql)

    assert facts.opaque
    assert facts.cte_writes == ()
    assert facts.diagnostic == DATA_CHANGE_QUERY
