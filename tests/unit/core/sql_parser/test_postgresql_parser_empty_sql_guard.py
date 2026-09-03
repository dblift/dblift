"""Tests for _identify_statement_type() empty/whitespace SQL guard (Story 19-2, NEW-BUG-35)."""

import pytest

from dblift.core.sql_model.base import SqlStatementType
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser


@pytest.mark.unit
class TestIdentifyStatementTypeEmptySqlGuard:
    def setup_method(self):
        self.parser = PostgreSqlRegexParser()

    def test_identify_statement_type_empty_string_returns_unknown(self):
        result = self.parser._identify_statement_type("")
        assert result == SqlStatementType.UNKNOWN

    def test_identify_statement_type_whitespace_only_returns_unknown(self):
        result = self.parser._identify_statement_type("   ")
        assert result == SqlStatementType.UNKNOWN

    def test_identify_statement_type_begin_returns_ddl(self):
        # Exercises the transaction keywords path adjacent to the new guard (M2/L1)
        result = self.parser._identify_statement_type("BEGIN")
        assert result == SqlStatementType.DDL

    def test_identify_statement_type_rollback_returns_ddl(self):
        result = self.parser._identify_statement_type("ROLLBACK")
        assert result == SqlStatementType.DDL
