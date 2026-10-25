"""DuckDB splitting keeps records without retaining the entire token stream."""

from dblift.core.sql_parser import lexical_tokenizer
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC


def test_split_does_not_retain_all_segment_tokens(monkeypatch):
    script = "SELECT 1;\n" * 640
    expected_count = len(LexicalTokenizer(script, spec=DUCKDB_SPEC).tokenize())

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
    records = LexicalEngine(DUCKDB_SPEC).split(script)

    assert len(records) == 640
    assert CountedToken.created == expected_count
    assert CountedToken.peak <= 32, f"retained {CountedToken.peak} live scanner tokens"
    assert CountedToken.live == 0
