"""The text DBLift sends to the server must match the text in the file.

``StatementSplitter`` used to reassemble each statement by joining token
text with heuristic spacing rules instead of slicing the original source.
That silently corrupted or re-spaced SQL that round-trips fine through a
native client — two adjacent string literals losing the whitespace between
them (turning a valid concatenation into one literal with a stray quote),
and ``DEFINER=`root`@`%``` gaining spaces around ``@`` that make
MySQL/MariaDB reject the statement outright. The same reassembly path is
shared by PostgreSQL, MySQL/MariaDB, SQL Server and Oracle, so all four
dialects are covered here — each with its own quirks (SQL Server's ``GO``
batch separator, Oracle's ``/`` PL/SQL terminator and SQL*Plus directives).
DB2, SQLite and DuckDB split statements with plain regex, never construct
a token-joining statement parser, and are unaffected by this class of bug.

Every statement here is checked for exact terminator-only difference from
the source: strip a trailing ``;``/``GO``/``/`` if present, nothing else.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
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
class TestPostgresCopyFromStdin:
    """``COPY ... FROM stdin`` data ends at its own ``\\.`` line — it does
    not glue onto whatever statement follows, which is what ``pg_dump``
    emits for table contents by default."""

    def test_data_block_ends_before_the_next_statement(self):
        sql = "COPY t (id, name) FROM stdin;\n1\talice\n2\tbob\n\\.\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, name) FROM stdin;",
            "1\talice\n2\tbob\n\\.",
            "SELECT 1;",
        ]

    def test_data_block_at_end_of_file_with_no_trailing_statement(self):
        sql = "COPY t (id, name) FROM stdin;\n1\talice\n\\.\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, name) FROM stdin;",
            "1\talice\n\\.",
        ]

    def test_backslash_dot_mid_line_is_not_a_terminator(self):
        """``\\.`` only ends the block at the start of a line; the same two
        characters inside a data value are ordinary data."""
        sql = "COPY t (id, note) FROM stdin;\n1\tO'Brien said \\. wasn't done\n\\.\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, note) FROM stdin;",
            "1\tO'Brien said \\. wasn't done\n\\.",
            "SELECT 1;",
        ]

    def test_data_line_resembling_sql_is_kept_as_data(self):
        """A data value that reads like SQL, semicolons included, is not
        re-parsed — the whole line is opaque data until the ``\\.`` line."""
        sql = "COPY t (id, cmd) FROM stdin;\n1\tSELECT 1; DROP TABLE t;\n\\.\nSELECT 2;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, cmd) FROM stdin;",
            "1\tSELECT 1; DROP TABLE t;\n\\.",
            "SELECT 2;",
        ]

    def test_empty_data_block(self):
        sql = "COPY t (id) FROM stdin;\n\\.\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id) FROM stdin;",
            "\\.",
            "SELECT 1;",
        ]

    def test_crlf_line_endings_through_the_data_block(self):
        sql = "COPY t (id, name) FROM stdin;\r\n1\talice\r\n2\tbob\r\n\\.\r\nSELECT 1;\r\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, name) FROM stdin;",
            "1\talice\r\n2\tbob\r\n\\.",
            "SELECT 1;",
        ]


@pytest.mark.unit
class TestPostgresMetaCommand:
    """``pg_dump`` wraps its output in ``\\restrict tok`` / ``\\unrestrict tok``
    (new enough versions). Those lines are psql client directives, not SQL —
    they must not glue onto the statement that follows, and executing
    nothing for them is harmless since they only scope the dump's own
    session."""

    def test_restrict_unrestrict_pair_skipped(self):
        sql = "\\restrict tok\n" "CREATE TABLE t (id int);\n" "SELECT 1;\n" "\\unrestrict tok\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["CREATE TABLE t (id int);", "SELECT 1;"]

    def test_meta_command_at_end_of_file_with_no_trailing_newline(self):
        sql = "SELECT 1;\n\\unrestrict tok"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["SELECT 1;"]

    def test_backslash_inside_string_literal_is_not_a_meta_command(self):
        """A string literal can contain a line starting with '\\' — it stays
        data, the same way a COPY row can start with '\\N'."""
        sql = "SELECT 'line one\n\\restrict fake\nline three' AS note;\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "SELECT 'line one\n\\restrict fake\nline three' AS note;",
            "SELECT 1;",
        ]

    def test_backslash_mid_line_is_not_a_meta_command(self):
        """Only a '\\' as the first non-whitespace character on a line is a
        meta-command; the unclaimed-character path handles this one
        unchanged, same as before this fix."""
        sql = "SELECT 1 \\restrict fake;\nSELECT 2;\n"

        with pytest.warns(UserWarning, match="unclaimed character"):
            stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["SELECT 1 \\restrict fake;", "SELECT 2;"]

    def test_copy_null_marker_stays_data(self):
        """'\\N' — SQL NULL in COPY's data format — must not be mistaken for
        a meta-command even though it starts a data line with '\\'."""
        sql = "COPY t (id, name) FROM stdin;\n1\t\\N\n2\tbob\n\\.\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == [
            "COPY t (id, name) FROM stdin;",
            "1\t\\N\n2\tbob\n\\.",
            "SELECT 1;",
        ]

    def test_meta_command_immediately_after_copy_block(self):
        sql = "COPY t (id) FROM stdin;\n1\n\\.\n\\unrestrict tok\nSELECT 1;\n"

        stmts = StatementSplitter("postgresql").split_statements(sql)

        assert stmts == ["COPY t (id) FROM stdin;", "1\n\\.", "SELECT 1;"]

    def test_unsupported_meta_command_is_refused_under_strict_tokenizer(self):
        """A meta-command with real effects (not just session scoping) is
        named and refused rather than silently skipped or silently glued
        onto the next statement."""
        sql = "\\i other.sql\nSELECT 1;\n"

        with pytest.raises(UnsupportedMetaCommandError, match=r"\\i"):
            StatementSplitter("postgresql").split_statements(sql, strict_tokenizer=True)

    @pytest.mark.parametrize(
        "dialect",
        [
            "aurora-postgresql",
            "citus",
            "cockroachdb",
            "neon",
            "redshift",
            "supabase",
            "timescaledb",
            "yugabytedb",
        ],
    )
    def test_restrict_pair_skipped_across_postgresql_wire_dialects(self, dialect):
        """All PostgreSQL-wire dialects share this tokenizer (see CHANGELOG's
        COPY-block entry for the same list)."""
        sql = "\\restrict tok\nCREATE TABLE t (id int);\n\\unrestrict tok\n"

        stmts = StatementSplitter(dialect).split_statements(sql)

        assert stmts == ["CREATE TABLE t (id int);"]


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


@pytest.mark.unit
class TestSqlServerVerbatim:
    def test_adjacent_string_literals_keep_original_whitespace(self):
        sql = "INSERT INTO t VALUES ('a '\n'b');\n"

        stmts = StatementSplitter("sqlserver").split_statements(sql)

        assert stmts == ["INSERT INTO t VALUES ('a '\n'b');"]

    def test_interior_comment_preserved(self):
        sql = "CREATE TABLE t (/* not nullable */ id INT NOT NULL);\n"

        stmts = StatementSplitter("sqlserver").split_statements(sql)

        assert stmts == ["CREATE TABLE t (/* not nullable */ id INT NOT NULL);"]

    def test_bracketed_identifier_with_space_and_percent_preserved(self):
        sql = "SELECT 1 FROM [my table % thing];\n"

        stmts = StatementSplitter("sqlserver").split_statements(sql)

        assert stmts == ["SELECT 1 FROM [my table % thing];"]

    def test_go_batch_separator_dropped_from_statement_with_content(self):
        """``GO`` is a batch separator for SSMS, not executable SQL — it must
        not appear in the statement it terminates, even though the statement's
        own ``;`` is kept."""
        sql = "SELECT 1\nGO\n"

        stmts = StatementSplitter("sqlserver").split_statements(sql)

        assert stmts == ["SELECT 1"]

    def test_repeated_go_produces_no_spurious_statement(self):
        """Two consecutive ``GO`` batch separators (e.g. a trailing blank
        batch) must not surface an empty statement between them."""
        sql = "CREATE TABLE t (id INT);\nGO\nGO\nSELECT 1;\n"

        stmts = StatementSplitter("sqlserver").split_statements(sql)

        assert stmts == ["CREATE TABLE t (id INT);", "SELECT 1;"]

    def test_comment_only_segment_still_dropped(self):
        assert StatementSplitter("sqlserver").split_statements("-- just a comment\n") == []
        assert StatementSplitter("sqlserver").split_statements("/* block comment */") == []


@pytest.mark.unit
class TestOracleVerbatim:
    def test_adjacent_string_literals_keep_original_whitespace(self):
        sql = "INSERT INTO t VALUES ('a '\n'b');\n"

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ["INSERT INTO t VALUES ('a '\n'b');"]

    def test_interior_comment_preserved(self):
        sql = "CREATE TABLE t (/* not nullable */ id NUMBER);\n"

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ["CREATE TABLE t (/* not nullable */ id NUMBER);"]

    def test_optimizer_hint_preserved(self):
        """``/*+ ... */`` is a hint, not an ordinary comment — dropping it
        silently changes the execution plan the statement asked for."""
        sql = "SELECT /*+ INDEX(t idx) */ * FROM t;\n"

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ["SELECT /*+ INDEX(t idx) */ * FROM t;"]

    def test_quoted_identifier_with_space_and_percent_preserved(self):
        sql = 'SELECT 1 FROM "my table % thing";\n'

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ['SELECT 1 FROM "my table % thing";']

    def test_plsql_block_slash_terminator_stripped_body_verbatim(self):
        """The trailing ``/`` (SQL*Plus PL/SQL execute marker) is stripped,
        same as before; nothing inside the block is re-spaced."""
        sql = "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\n"

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ["CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;"]

    def test_sqlplus_directive_still_filtered(self):
        """SQL*Plus client directives (e.g. SPOOL) are not valid Oracle SQL
        and are still dropped entirely — only the SQL statement remains,
        with its original spacing intact."""
        sql = "SPOOL /tmp/dblift_test.log;\nCREATE TABLE t (id NUMBER);\n"

        stmts = StatementSplitter("oracle").split_statements(sql)

        assert stmts == ["CREATE TABLE t (id NUMBER);"]

    def test_comment_only_segment_still_dropped(self):
        assert StatementSplitter("oracle").split_statements("-- just a comment\n") == []
        assert StatementSplitter("oracle").split_statements("/* block comment */") == []
