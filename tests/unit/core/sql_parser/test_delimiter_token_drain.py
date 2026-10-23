"""Delimiter scripts keep their records without retaining the scanner's tokens."""

from dataclasses import astuple, replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser import base_tokenizer, lexical_tokenizer
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement import analysis_sql, execution_strings
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from tests.support.facts_corpus import family_file, read_rows


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_engine_does_not_retain_delimiter_tokens_during_scan(monkeypatch, spec):
    script = "SELECT 1;\n" * 256
    expected_count = len(LexicalTokenizer(script, spec=spec).tokenize())

    class CountedToken(Token):
        __slots__ = ()
        created = 0
        live = 0
        peak = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            type(self).created += 1
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)

        def __del__(self):
            type(self).live -= 1

    monkeypatch.setattr(lexical_tokenizer, "Token", CountedToken)
    monkeypatch.setattr(base_tokenizer, "Token", CountedToken)
    parser = LexicalEngine(spec)._parser(script)

    assert len(parser.split()) == 256
    assert CountedToken.created == expected_count
    assert CountedToken.peak <= 16, f"retained {CountedToken.peak} live scanner tokens"
    assert parser.tokens == []


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_direct_delimiter_tokenize_still_returns_the_token_list(spec):
    tokenizer = LexicalTokenizer("SELECT 1; /* c */\n", spec=spec)
    tokens = tokenizer.tokenize()

    assert isinstance(tokens, list)
    assert [(token.type, token.text, token.pos) for token in tokens] == [
        (TokenType.KEYWORD, "SELECT", 0),
        (TokenType.KEYWORD, "1", 7),
        (TokenType.DELIMITER, ";", 8),
        (TokenType.COMMENT, "", 10),
    ]
    assert tokenizer.pos == len(tokenizer.sql)
    assert [record.text for record in tokenizer.delimiter_script.records] == ["SELECT 1"]


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
@pytest.mark.parametrize(
    "script, expected",
    [
        ("", []),
        (" \t\n", []),
        ("-- a comment\n/* another */\n", []),
        (
            "\ufeffSELECT 1;\r\n-- a comment\r\nDELIMITER //\r\n"
            "CREATE PROCEDURE p() BEGIN SELECT 2; END//\r\nDELIMITER ;\r\nSELECT 3",
            [
                "SELECT 1",
                "DELIMITER //",
                "CREATE PROCEDURE p() BEGIN SELECT 2; END",
                "DELIMITER ;",
                "SELECT 3",
            ],
        ),
    ],
    ids=["empty", "blanks", "comments", "bom-crlf-custom-delimiter"],
)
def test_engine_delimiter_scan_reaches_the_same_end_state(monkeypatch, spec, script, expected):
    scanned = []

    class TrackingTokenizer(LexicalTokenizer):
        def __init__(self, sql, *, spec):
            super().__init__(sql, spec=spec)
            self.token_reads = 0
            scanned.append(self)

        def _next_token(self):
            self.token_reads += 1
            return super()._next_token()

    direct = TrackingTokenizer(script, spec=spec)
    direct.tokenize()
    monkeypatch.setattr("dblift.core.sql_parser.lexical_engine.LexicalTokenizer", TrackingTokenizer)
    parser = LexicalEngine(spec)._parser(script)
    assert len(scanned) == 2
    engine_tokenizer = scanned[-1]

    def end_state(tokenizer):
        delimiter = tokenizer.delimiter_script
        return (
            tokenizer.pos,
            tokenizer.line,
            tokenizer.col,
            tokenizer.parens_depth,
            tokenizer.token_reads,
            tokenizer._delimiter,
            tokenizer._line_start,
            tokenizer.comments,
            delimiter.records,
            delimiter.removed,
            delimiter.open_hint,
            vars(delimiter.program),
        )

    assert end_state(engine_tokenizer) == end_state(direct)
    assert parser.split() == direct.delimiter_script.records
    assert [record.text for record in parser.split()] == expected


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_configured_refusal_precedes_late_open_string_without_returning_prefix(spec):
    strict = replace(
        spec,
        refused_character="\x01",
        refused_character_name="control",
        refused_reason="client rejects it",
    )
    script = "SELECT 1;\n" * 8 + "SELECT 'open\x01"

    with pytest.raises(UnsafeStatementSplitError) as caught:
        LexicalEngine(strict).split(script)

    assert str(caught.value) == ("a control character on line 9, column 13: client rejects it")


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_engine_preserves_direct_tokenizer_records_for_mysql_facts_corpus(spec):
    scripts = [row["sql"] for row in read_rows(family_file("mysql"))]
    assert len(scripts) >= 1500
    scripts.extend(["SELECT 1;\nSELECT 'open", "SELECT 1;\n/* open", "SELECT 1;\nDELIMITER\n"])
    engine = LexicalEngine(spec)

    for script in scripts:
        direct = LexicalTokenizer(script, spec=spec)
        try:
            direct.tokenize()
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
            for project in (engine.split, engine.split_statements, engine.split_for_analysis):
                with pytest.raises(type(error)) as caught:
                    project(script)
                assert str(caught.value) == str(error), script
        else:
            records = direct.delimiter_script.records
            assert [astuple(record) for record in engine.split(script)] == [
                astuple(record) for record in records
            ], script
            assert engine.split_statements(script) == execution_strings(records), script
            assert engine.split_for_analysis(script) == analysis_sql(records), script
