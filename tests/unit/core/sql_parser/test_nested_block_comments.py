"""Nested block comments (/* /* */ */) must not split into extra statements.

PostgreSQL, SQL Server, DuckDB and Db2 document/exhibit nested block comments, so a
``;`` inside a nested comment must stay inside it. MySQL/MariaDB, Oracle and
SQLite document that block comments do NOT nest (the first ``*/`` always
closes), so those dialects must keep splitting at the first ``*/`` — the
regression tests below pin that down. See CHANGELOG.md for citations.

Citus, TimescaleDB, Neon, Supabase, AlloyDB and Aurora PostgreSQL are
PostgreSQL itself (an extension or a hosted deployment), so PostgreSQL's
nesting is the same fact for them, not an inference. CockroachDB and
YugabyteDB are separate implementations of the wire protocol, not
PostgreSQL, so their nesting was checked directly against each engine
rather than inferred — both nest the same way PostgreSQL does. Redshift is
also a separate implementation and was checked against Redshift Serverless
1.0.485645 (docs/sql-parsing/redshift.md): it nests too.
"""

import unittest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

ISSUE_EXAMPLE = "/* outer /* inner */ DROP TABLE victim; still outer */\nSELECT 1;"

THREE_DEEP = "/* L1 /* L2 /* L3 */ DROP TABLE victim; still L3 */ still L2 */\n" "SELECT 1;"

# The inner "/*" never gets its own "*/": nesting-aware, the lone "*/" closes
# only the inner level, so the outer comment stays open to end of file.
UNTERMINATED_INNER = "/* outer /* inner */\nSELECT 1;"

# Three opens (L1, L2, L3), only two closes: the first closes L3, the second
# closes L2, and L1's own "*/" never arrives — nesting-aware, everything from
# there to end of file (including "SELECT 1;") stays inside the comment.
THREE_DEEP_UNTERMINATED_MIDDLE = "/* L1 /* L2 /* L3 */ DROP TABLE victim; still L3 */\n" "SELECT 1;"


def _regex_parser_for(dialect: str):
    """The dialect's statement-facts parser, built from its registered plugin."""
    return facts_parser(dialect)


class TestPostgresNestedBlockComments(unittest.TestCase):
    """PostgreSQL nests block comments (documented explicitly)."""

    def setUp(self):
        self.parser = facts_parser("postgresql")

    def test_issue_example_keeps_drop_inside_the_comment(self):
        stmts = self.parser.split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, ["SELECT 1;"])

    def test_two_deep(self):
        sql = "/* a /* b */ c */\nSELECT 1;"
        self.assertEqual(self.parser.split_statements(sql), ["SELECT 1;"])

    def test_three_deep(self):
        stmts = self.parser.split_statements(THREE_DEEP)
        self.assertEqual(stmts, ["SELECT 1;"])

    def test_unterminated_inner_comment_swallows_rest_of_file(self):
        # an unterminated block comment is refused, not swallowed
        with self.assertRaises(UnsafeStatementSplitError):
            self.parser.split_statements(UNTERMINATED_INNER)

    def test_three_deep_with_unterminated_middle_swallows_rest_of_file(self):
        # an unterminated block comment is refused, not swallowed
        with self.assertRaises(UnsafeStatementSplitError):
            self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE)

    def test_slash_star_inside_string_literal_is_not_a_comment(self):
        sql = "SELECT '/*' AS marker; SELECT 2;"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(stmts, ["SELECT '/*' AS marker;", "SELECT 2;"])

    def test_star_slash_inside_string_literal_is_not_a_comment(self):
        sql = "SELECT '*/' AS marker; SELECT 2;"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(stmts, ["SELECT '*/' AS marker;", "SELECT 2;"])

    def test_nested_comment_containing_a_dollar_quoted_body(self):
        sql = "/* outer /* inner $$ DROP TABLE victim; $$ */ still outer */\nSELECT 1;"
        stmts = self.parser.split_statements(sql)
        self.assertEqual(stmts, ["SELECT 1;"])

    def test_nested_comment_inside_a_do_dollar_quoted_block(self):
        # The comment lives inside the DO block's $$ ... $$ body, which is a
        # single dollar-quoted token regardless of comment markers within it
        # — this must keep working exactly as it does today.
        sql = (
            "DO $$\n"
            "BEGIN\n"
            "  /* outer /* inner */ still outer */\n"
            "  RAISE NOTICE 'x';\n"
            "END $$;\n"
            "SELECT 1;"
        )
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 2)
        self.assertIn("DO $$", stmts[0])
        self.assertEqual(stmts[1], "SELECT 1;")

    def test_comment_only_file_produces_no_statements(self):
        sql = "/* outer /* inner */ still outer */"
        self.assertEqual(self.parser.split_statements(sql), [])


class TestSqlServerNestedBlockComments(unittest.TestCase):
    """The server nests block comments, sqlcmd's lexer does not (docs/sql-parsing/sqlserver.md §3).

    The splitter reads as the client does: a batch ends at a ``GO`` line only, so a script
    without ``GO`` is one batch and its text goes to the server verbatim. The server reads the
    nested comment, so ``DROP TABLE victim`` never runs; an inner ``/*`` without its ``*/`` is
    the server's ``Msg 113``. Extraction still reads nested comments
    (``test_extraction_nested_block_comments.py``).
    """

    def setUp(self):
        self.parser = facts_parser("sqlserver")

    def test_issue_example_is_one_batch_the_server_reads_as_a_comment_and_a_select(self):
        self.assertEqual(self.parser.split_statements(ISSUE_EXAMPLE), [ISSUE_EXAMPLE])

    def test_three_deep(self):
        self.assertEqual(self.parser.split_statements(THREE_DEEP), [THREE_DEEP])

    def test_unterminated_inner_comment_is_one_batch_the_server_rejects(self):
        self.assertEqual(self.parser.split_statements(UNTERMINATED_INNER), [UNTERMINATED_INNER])

    def test_three_deep_with_unterminated_middle_is_one_batch_the_server_rejects(self):
        self.assertEqual(
            self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE),
            [THREE_DEEP_UNTERMINATED_MIDDLE],
        )

    def test_a_go_cut_inside_a_comment_the_server_holds_open_leaves_it_unclosed(self):
        # sqlcmd cuts at the second GO; the first half still has an open comment for the server
        script = "SELECT 1 /* a\nGO\n/* b */\nGO\n*/"
        self.assertEqual(self.parser.split_statements(script), ["SELECT 1 /* a\nGO\n/* b */", "*/"])


class TestDuckDBNestedBlockComments(unittest.TestCase):
    """DuckDB's parser is PostgreSQL-compatible and nests block comments.

    Unlike the tokenizer-based dialects, this splitter keeps comment text
    verbatim in the statement it precedes rather than stripping it — so a
    fully-nested comment yields one statement containing the whole input
    (there is no real split point left once the comment is not mistaken for
    one), never a statement that isolates ``DROP TABLE victim``.
    """

    def setUp(self):
        self.parser = facts_parser("duckdb")

    def test_issue_example_keeps_drop_inside_the_comment(self):
        stmts = self.parser.split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, [ISSUE_EXAMPLE.removesuffix(";")])

    def test_three_deep(self):
        stmts = self.parser.split_statements(THREE_DEEP)
        self.assertEqual(stmts, [THREE_DEEP.removesuffix(";")])

    def test_unterminated_inner_comment_is_refused(self):
        with self.assertRaises(UnsafeStatementSplitError):
            self.parser.split_statements(UNTERMINATED_INNER)

    def test_three_deep_with_unterminated_middle_is_refused(self):
        with self.assertRaises(UnsafeStatementSplitError):
            self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE)


class TestNonNestingDialectsUnchanged(unittest.TestCase):
    """MySQL/MariaDB, Oracle and SQLite document that comments do not nest:
    the first ``*/`` always closes, regardless of an inner ``/*``. These pin
    the pre-existing (and, per each vendor's docs, correct) behavior so a
    later change to the shared tokenizer can't silently nest these too.
    """

    def test_mysql_stops_at_first_close(self):
        stmts = facts_parser("mysql").split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))

    def test_oracle_stops_at_first_close(self):
        # The first "*/" closes, but the ";" followed by a stray "*/" is not the
        # last text on its line: spec §4 row 13 refuses it, so DROP TABLE victim
        # is never sent on its own.
        with self.assertRaises(UnsafeStatementSplitError):
            facts_parser("oracle").split_statements(ISSUE_EXAMPLE)

    def test_sqlite_stops_at_first_close(self):
        stmts = SQLiteFactsParser().split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))


class TestDb2NestedBlockComments(unittest.TestCase):
    """Db2 nests block comments, confirmed live on Db2 12.1 with both the
    CLP and the raw ``ibm_db`` driver: ``VALUES 1 /* a /* b */ c */``
    returns 1, and a CLP script whose nested comment holds ``;``,
    ``CREATE TABLE`` and ``DROP TABLE`` runs none of them. Like DuckDB's,
    this splitter keeps comment text in the statement it precedes, so a
    ``;`` inside the nested comment must not split there.
    """

    def setUp(self):
        self.parser = facts_parser("db2")

    def _live(self, statement):
        return strip_comments_preserving_quotes(
            statement, line_prefixes=["--"], has_block_comments=True, nested_block_comments=True
        )

    def test_tokenizer_declares_nesting(self):
        self.assertTrue(ProviderRegistry.get_quirks("db2").lexical_spec().nested_comments)

    def test_issue_example_keeps_drop_inside_the_comment(self):
        stmts = self.parser.split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, [ISSUE_EXAMPLE.rstrip(";")])

    def test_three_deep(self):
        stmts = self.parser.split_statements(THREE_DEEP)
        self.assertEqual(stmts, [THREE_DEEP.rstrip(";")])

    def test_unterminated_inner_comment_is_refused(self):
        # an unclosed block comment is refused, not swallowed (docs/sql-parsing/db2.md §4)
        with self.assertRaises(UnsafeStatementSplitError):
            self.parser.split_statements(UNTERMINATED_INNER)

    def test_comment_only_file_produces_no_statements(self):
        sql = "/* outer\n   /* inner */\n   still comment\n*/\n"
        self.assertEqual(self.parser.split_statements(sql), [])

    def test_nested_comment_with_statements_inside_is_not_split_or_run(self):
        sql = (
            "/* a /* b */ ; CREATE TABLE t_in (x INT); DROP TABLE t_keep; */\n"
            "CREATE TABLE t_after (x INT);\n"
            "CREATE TABLE t_after2 (x INT);"
        )
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 2, stmts)
        self.assertTrue(stmts[0].endswith("CREATE TABLE t_after (x INT)"), stmts)
        self.assertEqual(stmts[1], "CREATE TABLE t_after2 (x INT)")
        live = [self._live(s) for s in stmts]
        self.assertFalse(any("t_in" in s or "DROP" in s for s in live), live)

    def test_statement_ending_in_a_comment_is_kept(self):
        sql = (
            "/* x /* y */ DROP TABLE t_keep; */ CREATE TABLE t_after (x INT) /* tail */;\n"
            "CREATE TABLE t_after2 (x INT);"
        )
        stmts = self.parser.split_statements(sql)
        self.assertEqual(len(stmts), 2, stmts)
        self.assertIn("CREATE TABLE t_after (x INT)", stmts[0])
        self.assertEqual(stmts[1], "CREATE TABLE t_after2 (x INT)")

    def test_nested_comment_before_a_procedure_keeps_the_block_whole(self):
        sql = (
            "/* a /* b */ ; DROP TABLE t_keep; */\n"
            "--#SET TERMINATOR @\n"
            "CREATE PROCEDURE p1() BEGIN DECLARE v INT; SET v = 1; END@\n"
            "--#SET TERMINATOR ;\n"
            "CREATE TABLE t_after (x INT);"
        )
        stmts = self.parser.split_statements(sql)
        live = [self._live(s).strip() for s in stmts]
        self.assertEqual(
            live,
            [
                "CREATE PROCEDURE p1() BEGIN DECLARE v INT; SET v = 1; END",
                "CREATE TABLE t_after (x INT)",
            ],
        )

    def test_parse_sql_ignores_objects_inside_a_nested_comment(self):
        sql = (
            "/* a /* b */ ; CREATE TABLE t_in (x INT); DROP TABLE t_keep; */\n"
            "CREATE TABLE t_after (x INT);"
        )
        result = self.parser.parse_sql(sql)
        names = [o.name for stmt in result.statements for o in stmt.objects]
        self.assertEqual(names, ["T_AFTER"])


class TestPostgresWireCompatibleEnginesThatRunRealPostgres(unittest.TestCase):
    """Citus and TimescaleDB are PostgreSQL extensions; Neon, Supabase,
    AlloyDB and Aurora PostgreSQL are hosted deployments of the PostgreSQL
    engine itself (see ``_pg_compatible.py``'s module docstring). Nested
    block comments there are the same documented PostgreSQL fact, not an
    inference — so these keep the nesting reader with no separate citation.
    """

    def _assert_nests(self, dialect: str):
        stmts = _regex_parser_for(dialect).split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, ["SELECT 1;"], f"{dialect} should nest like PostgreSQL")

    def test_citus_nests(self):
        self._assert_nests("citus")

    def test_timescaledb_nests(self):
        self._assert_nests("timescaledb")

    def test_neon_nests(self):
        self._assert_nests("neon")

    def test_supabase_nests(self):
        self._assert_nests("supabase")

    def test_alloydb_nests(self):
        self._assert_nests("alloydb")

    def test_aurora_postgresql_nests(self):
        self._assert_nests("aurora-postgresql")


class TestCockroachdbYugabytedbNestBlockComments(unittest.TestCase):
    """CockroachDB and YugabyteDB speak the PostgreSQL wire protocol but are
    each their own implementation, not a PostgreSQL fork — wire
    compatibility is not grammar compatibility, so this was verified
    against each engine directly rather than inferred from either vendor's
    docs (neither addresses comment nesting) or from PostgreSQL's.

    Checked against a local single-node container of each engine
    (``cockroachdb/cockroach:latest-v23.2`` and
    ``yugabytedb/yugabyte:latest``): after ``CREATE TABLE victim (id INT)``,
    running ``/* outer /* inner */ DROP TABLE victim; still outer */ SELECT
    1;`` returned a single ``SELECT 1`` row with no error on both engines,
    and ``victim`` still existed afterwards — the whole span was read as one
    comment, so both nest block comments the same way PostgreSQL does.
    """

    def _assert_nests(self, dialect: str):
        stmts = _regex_parser_for(dialect).split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, ["SELECT 1;"], f"{dialect} should nest like PostgreSQL")

    def test_cockroachdb_nests(self):
        self._assert_nests("cockroachdb")

    def test_yugabytedb_nests(self):
        self._assert_nests("yugabytedb")


class TestRedshiftNestsBlockComments(unittest.TestCase):
    """Measured on Redshift Serverless 1.0.485645: ``/* a /* b */ c */ SELECT 1`` runs and
    ``/* a /* b */ SELECT 1`` is rejected as an unterminated comment, so the first ``*/``
    does not close an outer comment."""

    def test_redshift_nests(self):
        stmts = _regex_parser_for("redshift").split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, ["SELECT 1;"], "redshift should nest like PostgreSQL")


class TestBaseTokenizerNestingFlag(unittest.TestCase):
    """The shared tokenizer's block-comment nesting is opt-in per dialect."""

    def test_default_tokenizer_does_not_nest(self):
        tokens = BaseTokenizer("/* a /* b */ DROP c */ SELECT 1;").tokenize()
        # First "*/" closes the comment; "DROP c */ SELECT 1" is live code.
        self.assertTrue(any(t.text == "DROP" for t in tokens))

    def test_nesting_tokenizer_treats_whole_span_as_one_comment(self):
        class NestingTokenizer(BaseTokenizer):
            NESTED_BLOCK_COMMENTS = True

        tokens = NestingTokenizer("/* a /* b */ DROP c */ SELECT 1;").tokenize()
        self.assertFalse(any(t.text == "DROP" for t in tokens))


if __name__ == "__main__":
    unittest.main()
