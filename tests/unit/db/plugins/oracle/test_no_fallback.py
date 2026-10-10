"""The Oracle splitter forwards strict mode to its tokenizer and has no second splitter."""

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


def test_strict_tokenizer_reaches_the_oracle_tokenizer(monkeypatch):
    seen = []
    original = OracleTokenizer.__init__

    def record(self, sql, *args, **kwargs):
        seen.append(kwargs.get("strict_unknown_chars"))
        original(self, sql, *args, **kwargs)

    monkeypatch.setattr(OracleTokenizer, "__init__", record)
    SqlAnalyzer("oracle").split_statements("SELECT 1 FROM dual;", strict_tokenizer=True)
    assert True in seen
