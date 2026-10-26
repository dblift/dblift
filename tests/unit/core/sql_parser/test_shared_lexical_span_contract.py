"""Outputs a shared lexical fast path must preserve across client modes."""

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC


SCRIPT = "SELECT aa_9, 1.2, 'line\nx' /* c */ FROM t;\nSELECT 2;"


@pytest.mark.parametrize(
    "spec, expected_texts, comment_text, number_tokens",
    [
        (POSTGRESQL_SPEC, (SCRIPT[:41], "SELECT 2"), "", (("1.2", 13),)),
        (SQLITE_SPEC, (SCRIPT[:41], "SELECT 2"), "/* c */", (("1", 13), (".", 14), ("2", 15))),
        (SQLSERVER_SPEC, (SCRIPT,), "", (("1.2", 13),)),
        (MYSQL_SPEC, (SCRIPT[:41], "SELECT 2"), "", (("1", 13), (".", 14), ("2", 15))),
        (ORACLE_SPEC, (SCRIPT[:41], "SELECT 2"), "", (("1.2", 13),)),
        (DUCKDB_SPEC, (SCRIPT[:41], "SELECT 2"), "/* c */", (("1.2", 13),)),
        (DB2_SPEC, (SCRIPT[:41], "SELECT 2"), "/* c */", (("1", 13), (".", 14), ("2", 15))),
        (REDSHIFT_SPEC, (SCRIPT[:41], "SELECT 2"), "", (("1.2", 13),)),
    ],
)
def test_shared_scan_retains_client_tokens_and_records(
    spec, expected_texts, comment_text, number_tokens
):
    tokenizer = LexicalTokenizer(SCRIPT, spec=spec)
    tokens = tokenizer.tokenize()
    records = LexicalEngine(spec).split(SCRIPT)

    assert tuple(record.text for record in records) == expected_texts
    assert [(record.line, record.source_start, record.source_end) for record in records] == (
        [(1, 0, len(SCRIPT))]
        if spec is SQLSERVER_SPEC
        else [(1, 0, 43 if spec is DB2_SPEC else 42), (3, 43, 52)]
    )
    assert [(token.text, token.pos) for token in tokens if 13 <= token.pos < 16] == list(
        number_tokens
    )
    assert [
        (token.text, token.pos, token.line, token.col, token.parens_depth)
        for token in tokens
        if token.type == TokenType.COMMENT
    ] == [(comment_text, 27, 2, 4, 0)]
    assert [(token.pos, token.line, token.col) for token in tokens if token.text == "SELECT"] == [
        (0, 1, 1),
        (43, 3, 1),
    ]
