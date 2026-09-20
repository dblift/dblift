"""The text DBLift sends to the server must match the text in the file.

``StatementSplitter`` used to reassemble each statement by joining token
text with heuristic spacing rules instead of slicing the original source.
That silently corrupted or re-spaced SQL that round-trips fine through
``psql``/``mysql`` — two adjacent string literals losing the whitespace
between them (turning a valid concatenation into one literal with a stray
quote), and ``DEFINER=`root`@`%``` gaining spaces around ``@`` that make
MySQL/MariaDB reject the statement outright.

Every statement here is checked for exact terminator-only difference from
the source: strip a trailing ``;``/``GO`` if present, nothing else.
"""

from __future__ import annotations

import pytest

from dblift.core.migration.sql.statement_splitter import StatementSplitter


@pytest.mark.unit
class TestPostgresVerbatim:
    def test_adjacent_string_literals_keep_original_whitespace(self):
        """Standard SQL concatenates adjacent string literals; losing the
        newline between them turns 'a ' 'b' into the single literal
        "a 'b" instead of "a b"."""
        sql = "COMMENT ON TABLE t IS 'first part '\n    'second part';\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["COMMENT ON TABLE t IS 'first part '\n    'second part';"]

    def test_with_delete_returning_insert_not_respaced(self):
        sql = (
            "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id)\n"
            "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted;\n"
        )

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "WITH deleted AS (DELETE FROM src WHERE id = 1 RETURNING id)\n"
            "INSERT INTO app_logs(msg) SELECT 'removed ' || id FROM deleted;"
        ]

    def test_dollar_quoted_body_preserved_verbatim(self):
        sql = (
            "CREATE OR REPLACE FUNCTION greet()\n"
            "RETURNS TEXT AS $$\n"
            "BEGIN\n"
            "    RETURN  'Hello';   -- extra   spacing is source, not ours to fix\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
        )

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [sql.strip()]

    def test_quoted_identifier_with_space_and_percent_preserved(self):
        sql = 'SELECT 1 FROM "my table % thing";\n'

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ['SELECT 1 FROM "my table % thing";']

    def test_escape_string_preserved(self):
        sql = "SELECT E'a\\nb';\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["SELECT E'a\\nb';"]

    def test_interior_comment_preserved(self):
        sql = "CREATE TABLE t (/* not nullable */ id INT NOT NULL);\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["CREATE TABLE t (/* not nullable */ id INT NOT NULL);"]

    def test_comment_only_segment_still_dropped(self):
        """A plain leading comment with no code is still not a statement —
        only fixing corruption in real statements, not changing this."""
        assert StatementSplitter("postgresql").split_statements("-- just a comment\n") == []
        assert StatementSplitter("postgresql").split_statements("/* block comment */") == []


@pytest.mark.unit
class TestMySqlVerbatim:
    def test_definer_clause_not_respaced(self):
        sql = "CREATE DEFINER=`root`@`%` VIEW v AS SELECT id FROM parent;\n"

        stmts = StatementSplitter("mysql").split_statements(sql)

        assert stmts == ["CREATE DEFINER=`root`@`%` VIEW v AS SELECT id FROM parent"]

    def test_versioned_executable_comment_sent_verbatim(self):
        sql = "/*!40014 SET FOREIGN_KEY_CHECKS=0 */;\n"

        stmts = StatementSplitter("mysql").split_statements(sql)

        assert stmts == ["/*!40014 SET FOREIGN_KEY_CHECKS=0 */"]

    def test_mariadb_directive_comment_sent_verbatim(self):
        sql = "/*M!100001 SET STATEMENT sql_log_bin=0 FOR SET GLOBAL x=1 */;\n"

        stmts = StatementSplitter("mysql").split_statements(sql)

        assert stmts == ["/*M!100001 SET STATEMENT sql_log_bin=0 FOR SET GLOBAL x=1 */"]

    def test_interior_comment_preserved(self):
        sql = "CREATE TABLE t (/* not nullable */ id INT NOT NULL);\n"

        stmts = StatementSplitter("mysql").split_statements(sql)

        assert stmts == ["CREATE TABLE t (/* not nullable */ id INT NOT NULL)"]

    def test_quoted_identifier_with_space_and_percent_preserved(self):
        sql = "SELECT 1 FROM `my table % thing`;\n"

        stmts = StatementSplitter("mysql").split_statements(sql)

        assert stmts == ["SELECT 1 FROM `my table % thing`"]

    def test_comment_only_segment_still_dropped(self):
        assert StatementSplitter("mysql").split_statements("-- just a comment\n") == []
        assert StatementSplitter("mysql").split_statements("/* block comment */") == []
