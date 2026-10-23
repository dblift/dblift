"""The 5.0 SQL surface exposes statement records, not a text classifier."""

import pytest

from dblift.core.migration import sql as migration_sql
from dblift.core.migration.sql import execution_statement
from dblift.core.migration.sql.statement_splitter import StatementSplitter

pytestmark = pytest.mark.unit


def test_public_comment_only_helper_is_absent():
    assert not hasattr(migration_sql, "is_comment_only_statement")
    assert not hasattr(execution_statement, "is_comment_only_statement")


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_executable_comments_remain_statement_records(dialect):
    script = "/*!40014 SET FOREIGN_KEY_CHECKS=0 */"
    records = StatementSplitter(dialect).split(script)
    assert len(records) == 1
    assert records[0].kind == "sql"


@pytest.mark.parametrize("dialect", ["postgresql", "sqlserver", "db2"])
def test_nested_comment_only_scripts_have_no_records(dialect):
    assert StatementSplitter(dialect).split("/* outer /* inner */ tail */") == []
