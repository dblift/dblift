"""Outputs a shared lexical fast path must preserve across client modes."""

import hashlib
import json
import warnings

import pytest

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
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
SPECS = (
    POSTGRESQL_SPEC,
    SQLITE_SPEC,
    SQLSERVER_SPEC,
    MYSQL_SPEC,
    ORACLE_SPEC,
    DUCKDB_SPEC,
    DB2_SPEC,
    REDSHIFT_SPEC,
)


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


@pytest.mark.parametrize("spec", SPECS)
def test_span_reads_keep_the_base_readers_line_and_column(spec):
    source = "a\r\n\t'a''b'/* c */\u2028\xa0Z\n"
    shared = LexicalTokenizer(source, spec=spec)
    base = BaseTokenizer(shared.sql)
    for length in (2, 1, 3, 4, 2, 5, 3, 2, 9):
        assert shared.read(length) == base.read(length)
        assert (shared.pos, shared.line, shared.col) == (base.pos, base.line, base.col)


# Recorded from unchanged OSS develop 2ed1a71 with SQLGlot 30.24.0. Each digest covers
# public tokens (including every type, text, offset, line, column, and depth), records,
# execution strings, comment masking, and refusal class/message for the scripts below.
EDGE_SCRIPTS = (
    "SELECT\taa_9, 1.2, 'a''b' /* c */ FROM t;\r\nSELECT 2;",
    "SELECT 'a\r\nb';\r\n-- c\r\nSELECT 2;",
    "SELECT 1\n\xa0GO\nSELECT 2",
    "\f\nGO\nSELECT 2",
    "SELECT 1\u2028SELECT 2",
    "SELECT 1\xa0SELECT 2",
    "/* outer /* inner */ tail */ SELECT 1;",
    'SELECT "a""b", [c]]d] FROM t;',
    "SELECT 1\r\nGO 2\r\nSELECT 2",
)
EDGE_DIGESTS = {
    "postgresql": "75e62b8e473e61ab54a3b83b0b8e138bc8a6b36a412e111383119b097a4f4742",
    "sqlite": "5e36a370fe37ccd3a40827bfe4cd6e1204bd7cb35c9827794ab590a0c0119d02",
    "sqlserver": "1e8c0b0d669c03db85dd45a5da46db9beecfd0f310ee78dc872a76c3748fce06",
    "mysql": "6cdd3986c7920bf4d82ab7f1bf7992082bb9520afb087a7ba7a7880cdb95e426",
    "oracle": "5eff0ed97975b4c116677132c13b6f49dccad9e5d7e8ed69884ab45b922845ec",
    "duckdb": "133e739e628ac47004b7d80878cadeadf66db6122c9533ef752dcd3e48085fae",
    "db2": "ff9506492775da1e5100fdeb1c59ab97110597dd61c161f0e5e5d9fb9e314642",
    "redshift": "75e62b8e473e61ab54a3b83b0b8e138bc8a6b36a412e111383119b097a4f4742",
}


def _outcome(read):
    try:
        return read()
    except Exception as error:
        return [type(error).__name__, str(error)]


@pytest.mark.parametrize("spec", SPECS)
def test_edge_outputs_match_the_pre_fast_path_develop(spec):
    outcomes = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for source in EDGE_SCRIPTS:
            engine = LexicalEngine(spec)
            outcomes.append(
                [
                    _outcome(
                        lambda: [
                            (t.type.name, t.text, t.pos, t.line, t.col, t.parens_depth)
                            for t in LexicalTokenizer(source, spec=spec).tokenize()
                        ]
                    ),
                    _outcome(
                        lambda: [
                            (
                                r.text,
                                r.line,
                                r.terminator,
                                r.kind,
                                r.multi,
                                r.repeat,
                                r.source_start,
                                r.source_end,
                                r.analysis_statements,
                                r.execution_text,
                            )
                            for r in engine.split(source)
                        ]
                    ),
                    _outcome(lambda: LexicalEngine(spec).split_statements(source)),
                    _outcome(lambda: LexicalEngine(spec).blank_comments(source)),
                ]
            )
    encoded = json.dumps(outcomes, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == EDGE_DIGESTS[spec.name]
