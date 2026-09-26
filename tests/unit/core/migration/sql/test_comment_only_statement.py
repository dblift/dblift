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
