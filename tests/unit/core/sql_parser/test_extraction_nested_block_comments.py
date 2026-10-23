"""Object extraction must nest block comments only where splitting does.

The removed regex parser's comment stripper used to treat
``/* ... */`` as nesting for every dialect unconditionally, while statement
splitting already follows each engine's real rule (see
``test_nested_block_comments.py``). On a non-nesting engine such as MySQL, a
statement inside a nested comment was live code to the splitter but
invisible to extraction, so the two disagreed about what a migration
touches. See CHANGELOG.md.

Every assertion below checks the complete extracted object list (or an
exact name/count), not just whether one particular name is present or
absent: a parser that mis-scans the un-nested boundary can return a
different, garbled object rather than no object at all, and a membership
check (``any(o.name == "x" for o in objects)``) does not notice that —
it is still false either way. Only comparing the whole result catches a
malformed or extra object as well as a missing one.
"""

import unittest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

# "victim" only appears inside the nested comment, so finding it as an
# extracted object proves extraction (wrongly) looked past the first "*/".
NESTED_COMMENT_SQL = "/* outer /* inner */ CREATE TABLE victim (id INT); still outer */\nSELECT 1;"

# The issue's own reproduction: a commented-out CREATE followed by a real
# one, in a single call. Both halves of the defect show up here — the
# commented-out object must not appear, and the real one must.
ISSUE_REPRODUCTION_SQL = (
    "/* CREATE TABLE commented_out (id int); */ CREATE TABLE real_one (id int);"
)
LINE_COMMENT_REPRODUCTION_SQL = (
    "-- CREATE TABLE commented_out (id int);\nCREATE TABLE real_one (id int);"
)


def _regex_parser_for(dialect: str):
    """The dialect's statement-facts parser, built from its registered plugin."""
    return facts_parser(dialect)


def _splits_out_the_live_statement(dialect: str) -> bool:
    """True when this dialect's splitter treats ``CREATE TABLE victim`` as
    real code rather than comment (i.e. block comments do not nest here).

    SQLite and DuckDB split by tracking comment state without stripping
    comment text out of the returned statements (see
    ``test_nested_block_comments.py``), so a nested comment there still
    contains the "CREATE TABLE victim" substring verbatim even though it
    is not live. Stripping each returned statement's own comments before
    the check makes the signal accurate for those splitters too; other
    dialects already return comment-free text, so this is a no-op for them.
    """
    parser = _regex_parser_for(dialect)
    stmts = parser.split_statements(NESTED_COMMENT_SQL)
    quirks = ProviderRegistry.get_quirks(dialect)
    tokenizer = quirks.redaction_tokenizer()
    nests = tokenizer.NESTED_BLOCK_COMMENTS if tokenizer else quirks.lexical_spec().nested_comments
    if dialect == "duckdb":
        strip_comments = DuckDBQuirks().blank_comments
    else:

        def strip_comments(text: str) -> str:
            return strip_comments_preserving_quotes(
                text, line_prefixes=["--"], has_block_comments=True, nested_block_comments=nests
            )

    return any("CREATE TABLE victim" in strip_comments(s) for s in stmts)


def _assert_extracts_exactly_victim_or_nothing(
    testcase: unittest.TestCase, dialect: str, expect_live: bool
) -> None:
    """Assert the *complete* object list: exactly one object named
    ``victim`` when the splitter says the statement is live, otherwise
    exactly no objects at all. A malformed or extra object — not just a
    missing "victim" — fails this.
    """
    # get_affected_objects(): the public interface method for "what does
    # this statement touch", used uniformly across dialects.
    objects = _regex_parser_for(dialect).get_affected_objects(NESTED_COMMENT_SQL)
    if expect_live:
        testcase.assertEqual(
            len(objects), 1, f"{dialect}: expected exactly one object, got {objects!r}"
        )
        testcase.assertEqual(objects[0].name.lower(), "victim", f"{dialect}: got {objects!r}")
    else:
        testcase.assertEqual(objects, [], f"{dialect}: expected no objects, got {objects!r}")


class TestExtractionAgreesWithSplittingPerDialect(unittest.TestCase):
    """The test the issue asks for: whatever the splitter decided about the
    nested comment, extraction must reach the same verdict about the object
    inside it — the complete object list, not just whether one particular
    name shows up — for every dialect that ships a regex parser.
    """

    def _assert_agree(self, dialect: str):
        expect_live = _splits_out_the_live_statement(dialect)
        _assert_extracts_exactly_victim_or_nothing(self, dialect, expect_live)

    def test_postgresql(self):
        self._assert_agree("postgresql")

    def test_mysql(self):
        self._assert_agree("mysql")

    def test_mariadb(self):
        self._assert_agree("mariadb")

    def test_sqlserver(self):
        self._assert_agree("sqlserver")

    def test_sqlite(self):
        self._assert_agree("sqlite")

    def test_duckdb(self):
        self._assert_agree("duckdb")

    def test_db2(self):
        self._assert_agree("db2")

    def test_cockroachdb(self):
        self._assert_agree("cockroachdb")

    def test_yugabytedb(self):
        self._assert_agree("yugabytedb")

    def test_redshift(self):
        self._assert_agree("redshift")


class TestMySqlExtractionDoesNotNestBlockComments(unittest.TestCase):
    """MySQL/MariaDB document that block comments do not nest: the first
    ``*/`` always closes, so a statement after it is live code, not
    comment, and extraction must find exactly that object — the issue's
    own example.
    """

    def test_issue_example(self):
        sql = "/* a /* b */ CREATE TABLE t (id int); */"
        objects = facts_parser("mysql").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_nested_comment_leaves_live_statement_visible(self):
        objects = facts_parser("mysql").extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "victim")


class TestSqlServerExtractionNestsBlockComments(unittest.TestCase):
    """T-SQL documents nested comments are supported: the whole span up to
    the matching outer ``*/`` is one comment, so there must be no object
    at all — not just no object literally named ``victim`` (a scanner
    that mis-parses the un-nested boundary can return a different, garbled
    object instead of nothing, which a plain "is victim absent" check
    would miss).
    """

    def test_nested_comment_hides_the_statement(self):
        objects = facts_parser("sqlserver").extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(objects, [])


class TestDb2ExtractionNestsBlockComments(unittest.TestCase):
    """Db2 nests block comments (confirmed live, see
    ``test_nested_block_comments.py``): the whole span up to the matching
    outer ``*/`` is one comment, so there must be no object at all.
    """

    def test_nested_comment_hides_the_statement(self):
        objects = facts_parser("db2").extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(objects, [])

    def test_nested_comment_hides_create_and_drop_but_not_the_statement_after(self):
        sql = (
            "/* a /* b */ ; CREATE TABLE t_in (x INT); DROP TABLE t_keep; */\n"
            "CREATE TABLE t_after (x INT);"
        )
        objects = facts_parser("db2").extract_objects(sql)
        self.assertEqual([o.name for o in objects], ["T_AFTER"], objects)


class TestSQLiteExtractionDoesNotNestBlockComments(unittest.TestCase):
    """SQLite documents block comments do not nest, same as MySQL: the
    first ``*/`` always closes, so the commented-out statement must not be
    reported and the real one after it must.
    """

    def test_issue_example(self):
        objects = SQLiteFactsParser().extract_objects(ISSUE_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "real_one")

    def test_nested_comment_leaves_live_statement_visible(self):
        objects = SQLiteFactsParser().extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "victim")


class TestOracleExtractionDoesNotNestBlockComments(unittest.TestCase):
    """Oracle documents block comments do not nest, same as MySQL and
    SQLite: the first ``*/`` always closes, so the commented-out statement
    must not be reported and the real one after it must. Oracle upper-cases
    unquoted identifiers, hence "REAL_ONE" / "VICTIM".
    """

    def test_issue_example(self):
        objects = facts_parser("oracle").extract_objects(ISSUE_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "REAL_ONE")


class TestDuckDBExtractionNestsBlockComments(unittest.TestCase):
    """DuckDB documents nested block comments (PostgreSQL-compatible), same
    as SQL Server: a fully nested comment hides everything inside it, so
    there must be no object at all, not just no object named "victim".
    """

    def test_issue_example(self):
        objects = facts_parser("duckdb").extract_objects(ISSUE_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "real_one")

    def test_nested_comment_hides_the_statement(self):
        objects = facts_parser("duckdb").extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(objects, [])


class TestDuckDBScannerAndExtractionAgreeOnNestedComments(unittest.TestCase):
    """A nested comment remains one inert segment across scanner and object extraction."""

    def test_nested_comment_hides_the_statement_in_both_views(self):
        parser = facts_parser("duckdb")
        self.assertEqual(parser.split_for_extraction(NESTED_COMMENT_SQL), [NESTED_COMMENT_SQL[:-1]])
        self.assertEqual(parser.extract_objects(NESTED_COMMENT_SQL), [])


class TestLineCommentsAlsoHideTheCommentedStatement(unittest.TestCase):
    """The issue asks whether ``-- ...`` has the same effect as ``/* ... */``
    on SQLite and DuckDB. It does: a line comment hides the rest of its
    physical line regardless of block-comment nesting rules.
    """

    def test_sqlite(self):
        objects = SQLiteFactsParser().extract_objects(LINE_COMMENT_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "real_one")

    def test_duckdb(self):
        objects = facts_parser("duckdb").extract_objects(LINE_COMMENT_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "real_one")

    def test_oracle(self):
        objects = facts_parser("oracle").extract_objects(LINE_COMMENT_REPRODUCTION_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "REAL_ONE")


class TestExtractionReturnsEveryLiveObjectNotJustTheFirst(unittest.TestCase):
    """The issue's own reproduction returns one object where the input has
    two live statements. Confirm that is a consequence of the same
    comment-blind scan (``pattern.search()`` stopping at the first match)
    rather than a second, independent defect: once comments are stripped
    and every match is collected via ``finditer``, two live CREATE TABLEs
    yield two objects, not one.
    """

    SQL = "CREATE TABLE first_one (id int); CREATE TABLE second_one (id int);"

    def test_sqlite(self):
        objects = SQLiteFactsParser().extract_objects(self.SQL)
        self.assertEqual([o.name for o in objects], ["first_one", "second_one"])

    def test_duckdb(self):
        objects = facts_parser("duckdb").extract_objects(self.SQL)
        self.assertEqual([o.name for o in objects], ["first_one", "second_one"])


class TestUnterminatedInnerCommentAgreesWithSplitting(unittest.TestCase):
    """An inner ``/*`` that never gets its own ``*/`` behaves differently
    per dialect: nesting-aware, the lone ``*/`` closes only the inner level
    and the outer comment stays open to end of file; non-nesting, that same
    ``*/`` closes the whole comment and the remaining text is live code.
    """

    UNTERMINATED_INNER = "/* outer /* inner */ CREATE TABLE victim (id INT);"

    def test_postgresql_refuses_an_unterminated_nested_comment(self):
        with self.assertRaises(UnsafeStatementSplitError):
            facts_parser("postgresql").extract_objects(self.UNTERMINATED_INNER)

    def test_mysql_closes_at_first_marker_exposes_statement(self):
        objects = facts_parser("mysql").extract_objects(self.UNTERMINATED_INNER)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "victim")

    def test_sqlite_closes_at_first_marker_exposes_statement(self):
        objects = SQLiteFactsParser().extract_objects(self.UNTERMINATED_INNER)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "victim")

    def test_oracle_closes_at_first_marker_exposes_statement(self):
        objects = facts_parser("oracle").extract_objects(self.UNTERMINATED_INNER)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "VICTIM")

    def test_duckdb_stays_open_and_the_script_is_refused(self):
        with self.assertRaises(UnsafeStatementSplitError):
            facts_parser("duckdb").extract_objects(self.UNTERMINATED_INNER)


class TestQuotedCommentMarkersSurviveDialectAwareStripping(unittest.TestCase):
    """Nesting-awareness must not regress the existing quote-preservation
    behaviour: ``/*``/``*/`` inside a string literal is still not a
    comment marker, on both a nesting and a non-nesting dialect.
    """

    def test_slash_star_inside_string_on_mysql(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '/*'); SELECT 1;"
        objects = facts_parser("mysql").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_star_slash_inside_string_on_postgresql(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '*/'); SELECT 1;"
        objects = facts_parser("postgresql").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_slash_star_inside_string_on_sqlite(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '/*'); SELECT 1;"
        objects = SQLiteFactsParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_star_slash_inside_string_on_duckdb(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '*/'); SELECT 1;"
        objects = facts_parser("duckdb").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_slash_star_inside_string_on_oracle(self):
        sql = "CREATE TABLE t (note VARCHAR2(10) DEFAULT '/*');\nSELECT 1 FROM DUAL;"
        objects = facts_parser("oracle").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "T")

    def test_star_slash_inside_string_on_oracle(self):
        sql = "CREATE TABLE t (note VARCHAR2(10) DEFAULT '*/');\nSELECT 1 FROM DUAL;"
        objects = facts_parser("oracle").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "T")


class TestCommentContainingSemicolon(unittest.TestCase):
    """A ``;`` inside a block comment must not be mistaken for a statement
    boundary by extraction either.
    """

    def test_mysql_semicolon_inside_comment_is_not_a_boundary(self):
        sql = "/* has a ; inside */ CREATE TABLE t (id int);"
        objects = facts_parser("mysql").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_sqlite_semicolon_inside_comment_is_not_a_boundary(self):
        sql = "/* has a ; inside */ CREATE TABLE t (id int);"
        objects = SQLiteFactsParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_duckdb_semicolon_inside_comment_is_not_a_boundary(self):
        sql = "/* has a ; inside */ CREATE TABLE t (id int);"
        objects = facts_parser("duckdb").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_oracle_semicolon_inside_comment_is_not_a_boundary(self):
        sql = "/* has a ; inside */ CREATE TABLE t (id int);"
        objects = facts_parser("oracle").extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "T")


if __name__ == "__main__":
    unittest.main()
