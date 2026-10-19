"""Public comment classification matches migration execution semantics."""

import pytest

from dblift.core.migration import sql as migration_sql


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("", True),
        (" \n\t", True),
        ("/* block */ -- line\n/* next */", True),
        ("SELECT 1", False),
        ("-- intro\nSELECT 1", False),
        ("/* intro */ CREATE TABLE t (id INT)", False),
        ("/*!40014 SET FOREIGN_KEY_CHECKS=0 */", False),
        ("/*M!100001 SET STATEMENT sql_log_bin=0 FOR SET GLOBAL x=1 */", False),
    ],
)
def test_public_comment_check_preserves_executable_directives(statement, expected):
    assert migration_sql.is_comment_only_statement(statement) is expected


@pytest.mark.parametrize(
    ("statement", "nested", "expected"),
    [
        ("/* outer /* nested */ still comment */", False, False),
        ("/* outer /* nested */ still comment */", True, True),
        ("/* outer /* nested */ still comment */ -- tail\n", True, True),
        ("/* outer /* nested */ still comment */ SELECT 1", True, False),
        ("/* a */ still */", True, False),
    ],
)
def test_comment_check_follows_dialect_nesting_rule(statement, nested, expected):
    assert (
        migration_sql.is_comment_only_statement(statement, nested_block_comments=nested) is expected
    )


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("\xa0", False),
        ("\x0c", False),
        ("\xa0 -- c", False),
        ("\xa0/* c */", False),
        (" \t\r\n-- c", True),
        ("", True),
    ],
)
def test_a_dialect_that_keeps_a_character_does_not_read_it_as_white_space(statement, expected):
    blanks = " \t\n\r"
    assert migration_sql.is_comment_only_statement(statement, blanks=blanks) is expected


@pytest.mark.parametrize("statement", ["\xa0", "\x0b", " ", "\x85", "\xa0 -- c"])
def test_without_blanks_every_white_space_character_still_empties_a_statement(statement):
    assert migration_sql.is_comment_only_statement(statement) is True


@pytest.mark.parametrize("dialect_flags", [{}, {"hash_comments": True}])
@pytest.mark.parametrize("nested", [False, True])
def test_a_line_comment_hides_a_block_opener_from_the_block_scan(dialect_flags, nested):
    sql = "-- see /* x\nCREATE TABLE t (c int /* y */)"
    assert (
        migration_sql.is_comment_only_statement(sql, nested_block_comments=nested, **dialect_flags)
        is False
    )


def test_a_hash_comment_hides_a_block_opener():
    sql = "# see /* x\nCREATE TABLE t (c int /* y */)"
    assert migration_sql.is_comment_only_statement(sql, hash_comments=True) is False


@pytest.mark.parametrize(
    ("statement", "kwargs", "expected"),
    [
        ("-- ends */ here\n-- more", {}, True),
        ("# ends */ here", {"hash_comments": True}, True),
        ("/* has -- inside */", {}, True),
        ("/* has # inside */", {"hash_comments": True}, True),
        ("/* has -- inside */ SELECT 1", {}, False),
        ("SELECT '/* not a comment */'", {}, False),
        ("SELECT '-- nor this'", {}, False),
        ("SELECT '# nor this'", {"hash_comments": True}, False),
        ("/* a */ # b\n/* c */", {"hash_comments": True}, True),
        ("# not a comment here", {}, False),
        ("/*!40014 SET x=1 */", {}, False),
        ("-- c\n/*!40014 SET x=1 */", {}, False),
    ],
)
def test_comments_are_stripped_in_source_order(statement, kwargs, expected):
    assert migration_sql.is_comment_only_statement(statement, **kwargs) is expected
