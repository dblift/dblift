"""Nested block comments (/* /* */ */) must not split into extra statements.

PostgreSQL, SQL Server and DuckDB document/exhibit nested block comments, so a
``;`` inside a nested comment must stay inside it. MySQL/MariaDB, Oracle and
SQLite document that block comments do NOT nest (the first ``*/`` always
closes), so those dialects must keep splitting at the first ``*/`` — the
regression tests below pin that down. See CHANGELOG.md for citations.

Citus, TimescaleDB, Neon, Supabase, AlloyDB and Aurora PostgreSQL are
PostgreSQL itself (an extension or a hosted deployment), so PostgreSQL's
nesting is the same fact for them, not an inference. Redshift, CockroachDB
and YugabyteDB are each their own implementation of the wire protocol, not
PostgreSQL, and no vendor documentation addressing comment nesting was found
for any of the three — they keep the non-nesting reader rather than
inheriting PostgreSQL's behavior without evidence.
"""

import unittest

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
    PostgreSqlRegexParser,
)
from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import (
    SqlServerRegexParser,
)
from dblift.db.provider_registry import ProviderRegistry

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
    """Instantiate the dialect's registered regex parser via ProviderRegistry,
    exactly as the runtime resolves it — not by importing a parser class
    directly, so these tests catch a wrong quirks-level wiring too.
    """
    return ProviderRegistry.get_quirks(dialect).parser_class("regex")()


class TestPostgresNestedBlockComments(unittest.TestCase):
    """PostgreSQL nests block comments (documented explicitly)."""

    def setUp(self):
        self.parser = PostgreSqlRegexParser()

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
        stmts = self.parser.split_statements(UNTERMINATED_INNER)
        self.assertEqual(stmts, [])

    def test_three_deep_with_unterminated_middle_swallows_rest_of_file(self):
        stmts = self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE)
        self.assertEqual(stmts, [])

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
    """T-SQL documents that nested comments are supported."""

    def setUp(self):
        self.parser = SqlServerRegexParser()

    def test_issue_example_keeps_drop_inside_the_comment(self):
        stmts = self.parser.split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, ["SELECT 1;"])

    def test_three_deep(self):
        stmts = self.parser.split_statements(THREE_DEEP)
        self.assertEqual(stmts, ["SELECT 1;"])

    def test_unterminated_inner_comment_swallows_rest_of_file(self):
        stmts = self.parser.split_statements(UNTERMINATED_INNER)
        self.assertEqual(stmts, [])

    def test_three_deep_with_unterminated_middle_swallows_rest_of_file(self):
        stmts = self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE)
        self.assertEqual(stmts, [])


class TestDuckDBNestedBlockComments(unittest.TestCase):
    """DuckDB's parser is PostgreSQL-compatible and nests block comments.

    Unlike the tokenizer-based dialects, this splitter keeps comment text
    verbatim in the statement it precedes rather than stripping it — so a
    fully-nested comment yields one statement containing the whole input
    (there is no real split point left once the comment is not mistaken for
    one), never a statement that isolates ``DROP TABLE victim``.
    """

    def setUp(self):
        self.parser = DuckDBRegexParser()

    def test_issue_example_keeps_drop_inside_the_comment(self):
        stmts = self.parser.split_statements(ISSUE_EXAMPLE)
        self.assertEqual(stmts, [ISSUE_EXAMPLE])

    def test_three_deep(self):
        stmts = self.parser.split_statements(THREE_DEEP)
        self.assertEqual(stmts, [THREE_DEEP])

    def test_unterminated_inner_comment_swallows_rest_of_file(self):
        stmts = self.parser.split_statements(UNTERMINATED_INNER)
        self.assertEqual(stmts, [UNTERMINATED_INNER])

    def test_three_deep_with_unterminated_middle_swallows_rest_of_file(self):
        stmts = self.parser.split_statements(THREE_DEEP_UNTERMINATED_MIDDLE)
        self.assertEqual(stmts, [THREE_DEEP_UNTERMINATED_MIDDLE])


class TestNonNestingDialectsUnchanged(unittest.TestCase):
    """MySQL/MariaDB, Oracle and SQLite document that comments do not nest:
    the first ``*/`` always closes, regardless of an inner ``/*``. These pin
    the pre-existing (and, per each vendor's docs, correct) behavior so a
    later change to the shared tokenizer can't silently nest these too.
    """

    def test_mysql_stops_at_first_close(self):
        stmts = MySqlRegexParser().split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))

    def test_oracle_stops_at_first_close(self):
        stmts = OracleParser().split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))

    def test_sqlite_stops_at_first_close(self):
        stmts = SQLiteRegexParser().split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))


class TestDb2Unchanged(unittest.TestCase):
    """Db2 nested-bracketed-comment support could not be verified against a
    live engine (see CHANGELOG.md); this pins current behavior so a change
    is deliberate rather than incidental.
    """

    def test_stops_at_first_close(self):
        stmts = DB2RegexParser().split_statements(ISSUE_EXAMPLE)
        self.assertTrue(any("DROP TABLE victim" in s for s in stmts))


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


class TestPostgresWireCompatibleEnginesThatAreSeparateImplementations(unittest.TestCase):
    """Redshift, CockroachDB and YugabyteDB speak the PostgreSQL wire
    protocol but are each their own implementation, not PostgreSQL itself.
    No vendor documentation addressing nested block comments was found for
    any of the three (see CHANGELOG.md and each dialect's ``quirks.py`` /
    ``plugin.py``), so — per this repo's rule against asserting engine
    behavior without evidence — they keep the pre-fix, non-nesting reader
    instead of inheriting PostgreSQL's documented nesting blind.
    """

    def _assert_does_not_nest(self, dialect: str):
        stmts = _regex_parser_for(dialect).split_statements(ISSUE_EXAMPLE)
        self.assertTrue(
            any("DROP TABLE victim" in s for s in stmts),
            f"{dialect} should still split at the first */",
        )

    def test_redshift_does_not_nest(self):
        self._assert_does_not_nest("redshift")

    def test_cockroachdb_does_not_nest(self):
        self._assert_does_not_nest("cockroachdb")

    def test_yugabytedb_does_not_nest(self):
        self._assert_does_not_nest("yugabytedb")


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
