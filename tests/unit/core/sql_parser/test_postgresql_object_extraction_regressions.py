"""Regression tests for PostgreSQL object extraction via ``get_affected_objects``.

Covers two defects in comment handling and ``ALTER TABLE ONLY`` support,
plus the surrounding quoting/comment scenarios that exercise the same code
paths (``EnhancedRegexParser.extract_objects`` and the PostgreSQL
``drop_table`` / ``alter_table`` object patterns).
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import (
    PostgreSqlRegexParser,
)


@pytest.mark.unit
class TestLeadingCommentObjectExtraction:
    """A comment must never be mistaken for the statement it precedes."""

    def setup_method(self):
        self.parser = SqlParserFactory("postgresql")

    def test_leading_line_comment_mentioning_alter_table(self):
        sql = "-- ALTER TABLE in a comment\nDROP TABLE IF EXISTS `x`.`orders`;"
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.TABLE
        assert objects[0].name == "orders"
        assert objects[0].schema == "x"

    def test_leading_block_comment(self):
        sql = '/* migration header */\nDROP TABLE IF EXISTS "s"."orders";'
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_comment_between_verb_and_object(self):
        sql = 'DROP TABLE /* keep */ "s"."orders";'
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_comment_containing_drop_table_words(self):
        sql = (
            '-- DROP TABLE old_orders, nothing to see\nALTER TABLE "s"."orders" ADD COLUMN "x" INT;'
        )
        objects = self.parser.get_affected_objects(sql)

        names = {o.name for o in objects}
        assert "old_orders" not in names
        assert "orders" in names

    def test_statement_that_is_only_a_comment(self):
        assert self.parser.get_affected_objects("-- just a comment, nothing else") == []
        assert self.parser.get_affected_objects("/* only a block comment */") == []


@pytest.mark.unit
class TestAlterTableOnly:
    """``ALTER TABLE ONLY`` confines the change to the named table; ``ONLY``
    is not itself an object."""

    def setup_method(self):
        self.parser = SqlParserFactory("postgresql")

    def test_quoted_schema_qualified(self):
        sql = 'ALTER TABLE ONLY "s"."orders" DROP COLUMN "total";'
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.TABLE
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_unquoted_unqualified(self):
        sql = "ALTER TABLE ONLY orders DROP COLUMN total;"
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name.lower() == "orders"

    def test_unquoted_schema_qualified(self):
        sql = "ALTER TABLE ONLY s.orders DROP COLUMN total;"
        objects = self.parser.get_affected_objects(sql)

        names = [o.name.lower() for o in objects]
        assert "only" not in names
        assert "orders" in names

    def test_if_exists_only_combination(self):
        sql = 'ALTER TABLE IF EXISTS ONLY "s"."orders" DROP COLUMN "total";'
        objects = self.parser.get_affected_objects(sql)

        names = [o.name.lower() for o in objects]
        assert "only" not in names
        assert "orders" in names


@pytest.mark.unit
class TestQuotingVariants:
    """DROP TABLE must tolerate the quoting styles a migration may carry,
    without losing the underlying object."""

    def setup_method(self):
        self.parser = SqlParserFactory("postgresql")

    def test_backtick_quoting(self):
        sql = "DROP TABLE IF EXISTS `x`.`orders`;"
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "x"

    def test_bracket_quoting(self):
        sql = "DROP TABLE IF EXISTS [x].[orders];"
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "x"

    def test_double_quoted_schema_containing_a_dot(self):
        sql = 'DROP TABLE IF EXISTS "my.schema"."orders";'
        objects = self.parser.get_affected_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "my.schema"

    def test_multiple_tables_if_exists(self):
        sql = "DROP TABLE IF EXISTS a, b;"
        objects = self.parser.get_affected_objects(sql)

        names = {o.name.lower() for o in objects}
        assert names == {"a", "b"}


@pytest.mark.unit
class TestCommentStrippingIsQuoteAware:
    """The comment strip in ``extract_objects`` must not treat a comment
    marker inside a quoted span as a real comment. Exercised directly
    against the regex parsers (not ``SqlParserFactory``'s hybrid parser),
    because the hybrid parser lets sqlglot parse these statements and
    merges its correct result back in, masking a broken regex fallback."""

    def setup_method(self):
        self.postgres = PostgreSqlRegexParser()
        self.mysql = MySqlRegexParser()

    def test_quoted_identifier_containing_double_dash(self):
        sql = 'ALTER TABLE "a--b" ADD COLUMN x INT;'
        objects = self.postgres.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "a--b"

    def test_quoted_identifier_containing_block_comment_start(self):
        # A trailing real block comment is required to prove this case: a
        # naive strip's non-greedy "/\*.*?\*/" finds no closing "*/" at all
        # without it and leaves the string untouched by accident, rather
        # than because it is quote-aware.
        sql = 'ALTER TABLE "a/*b" ADD COLUMN x INT; /* trailing */'
        objects = self.postgres.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "a/*b"

    def test_double_dash_inside_single_quoted_string_before_the_identifier(self):
        sql = 'SELECT \'pre--fix\' AS note; DROP TABLE IF EXISTS "s"."orders";'
        objects = self.postgres.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_dollar_quoted_body_containing_double_dash(self):
        # Kept on a single line (no newline after "--"): a naive line-comment
        # strip stops only at a newline, so without one it would consume
        # everything to the end of the string once it (wrongly) starts a
        # comment inside the dollar-quoted body, hiding the ALTER TABLE
        # that follows.
        sql = (
            "CREATE FUNCTION foo() RETURNS INT AS $$ BEGIN -- note $$ LANGUAGE plpgsql; "
            'ALTER TABLE "s"."orders" ADD COLUMN "x" INT; END; $$;'
        )
        objects = self.postgres.extract_objects(sql)

        names = {(o.name, o.schema) for o in objects}
        assert ("orders", "s") in names
        assert ("foo", None) in names

    def test_mysql_hash_comment_marker_inside_backtick_quoted_identifier(self):
        sql = "ALTER TABLE `a#b` ADD COLUMN x INT;"
        objects = self.mysql.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "a#b"

    def test_nested_block_comment_between_verb_and_identifier(self):
        sql = 'ALTER TABLE /* outer /* inner */ x */ "s"."orders" ADD COLUMN c INT;'
        objects = self.postgres.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_nested_block_comment_spanning_up_to_the_identifier(self):
        sql = 'ALTER TABLE ONLY /* a /* b */ c */ "s"."orders" ADD COLUMN x INT;'
        objects = self.postgres.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "orders"
        assert objects[0].schema == "s"

    def test_unterminated_nested_block_comment_consumes_to_end(self):
        # No closing "*/" at all: everything after the opening "/*" is
        # comment, so there is no real statement left to find an object in.
        sql = 'ALTER TABLE /* outer /* inner never closes "s"."orders" ADD COLUMN c INT;'
        objects = self.postgres.extract_objects(sql)

        assert objects == []
