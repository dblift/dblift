"""Object extraction must nest block comments only where splitting does.

``EnhancedRegexParser._strip_comments_preserving_quotes`` used to treat
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

from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
    PostgreSqlRegexParser,
)
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import (
    SqlServerRegexParser,
)
from dblift.db.provider_registry import ProviderRegistry

# "victim" only appears inside the nested comment, so finding it as an
# extracted object proves extraction (wrongly) looked past the first "*/".
NESTED_COMMENT_SQL = "/* outer /* inner */ CREATE TABLE victim (id INT); still outer */\nSELECT 1;"


def _regex_parser_for(dialect: str):
    """Resolve the dialect's regex parser via ``ProviderRegistry``, exactly
    as the runtime does (mirrors ``test_nested_block_comments.py``'s
    helper), so a wrong quirks-level wiring is caught too, not just a wrong
    parser class.
    """
    return ProviderRegistry.get_quirks(dialect).parser_class("regex")()


def _splits_out_the_live_statement(dialect: str) -> bool:
    """True when this dialect's splitter treats ``CREATE TABLE victim`` as
    real code rather than comment (i.e. block comments do not nest here).
    """
    stmts = _regex_parser_for(dialect).split_statements(NESTED_COMMENT_SQL)
    return any("CREATE TABLE victim" in s for s in stmts)


def _assert_extracts_exactly_victim_or_nothing(
    testcase: unittest.TestCase, dialect: str, expect_live: bool
) -> None:
    """Assert the *complete* object list: exactly one object named
    ``victim`` when the splitter says the statement is live, otherwise
    exactly no objects at all. A malformed or extra object — not just a
    missing "victim" — fails this.
    """
    # get_affected_objects(), not extract_objects(): it's the public
    # interface method for "what does this statement touch", and Oracle's
    # accurate extraction only lives behind that name (extract_objects()
    # falls through to a generic base-class stub for OracleParser).
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

    def test_oracle(self):
        self._assert_agree("oracle")

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
        objects = MySqlRegexParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_nested_comment_leaves_live_statement_visible(self):
        objects = MySqlRegexParser().extract_objects(NESTED_COMMENT_SQL)
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
        objects = SqlServerRegexParser().extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(objects, [])


class TestDb2ExtractionDoesNotNestBlockComments(unittest.TestCase):
    """Db2 nesting was left unverified and kept non-nesting (see
    CHANGELOG.md); extraction must match, not assume nesting. Db2
    upper-cases unquoted identifiers, hence "VICTIM".
    """

    def test_nested_comment_leaves_live_statement_visible(self):
        objects = DB2RegexParser().extract_objects(NESTED_COMMENT_SQL)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name, "VICTIM")


class TestUnterminatedInnerCommentAgreesWithSplitting(unittest.TestCase):
    """An inner ``/*`` that never gets its own ``*/`` behaves differently
    per dialect: nesting-aware, the lone ``*/`` closes only the inner level
    and the outer comment stays open to end of file; non-nesting, that same
    ``*/`` closes the whole comment and the remaining text is live code.
    """

    UNTERMINATED_INNER = "/* outer /* inner */ CREATE TABLE victim (id INT);"

    def test_postgresql_stays_open_hides_everything(self):
        objects = PostgreSqlRegexParser().extract_objects(self.UNTERMINATED_INNER)
        self.assertEqual(objects, [])

    def test_mysql_closes_at_first_marker_exposes_statement(self):
        objects = MySqlRegexParser().extract_objects(self.UNTERMINATED_INNER)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "victim")


class TestQuotedCommentMarkersSurviveDialectAwareStripping(unittest.TestCase):
    """Nesting-awareness must not regress the existing quote-preservation
    behaviour: ``/*``/``*/`` inside a string literal is still not a
    comment marker, on both a nesting and a non-nesting dialect.
    """

    def test_slash_star_inside_string_on_mysql(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '/*'); SELECT 1;"
        objects = MySqlRegexParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")

    def test_star_slash_inside_string_on_postgresql(self):
        sql = "CREATE TABLE t (note VARCHAR(10) DEFAULT '*/'); SELECT 1;"
        objects = PostgreSqlRegexParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")


class TestCommentContainingSemicolon(unittest.TestCase):
    """A ``;`` inside a block comment must not be mistaken for a statement
    boundary by extraction either.
    """

    def test_mysql_semicolon_inside_comment_is_not_a_boundary(self):
        sql = "/* has a ; inside */ CREATE TABLE t (id int);"
        objects = MySqlRegexParser().extract_objects(sql)
        self.assertEqual(len(objects), 1, objects)
        self.assertEqual(objects[0].name.lower(), "t")


if __name__ == "__main__":
    unittest.main()
