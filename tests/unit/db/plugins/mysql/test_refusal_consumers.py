"""What the callers of the execution split do with a MySQL or MariaDB script it refuses."""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.sql.migration_sql_parser import parse_migration_sql
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from tests.unit._migration_factory import make_migration

SCRIPT = "UPDATE t SET a = 1;\nSELECT a FROM t\\G\nUPDATE t SET a = 2;\n"
DIALECTS = ["mysql", "mariadb"]


def _migration(dialect: str, content: str = SCRIPT) -> Migration:
    return make_migration(
        script_name="V1__update.sql",
        content=content,
        version="1",
        description="update",
        type=MigrationType.SQL,
        dialect=dialect,
    )


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_executable_statement_list_is_empty_and_the_error_names_the_command(
    dialect: str,
) -> None:
    # dry-run and plan listings call get_executable_sql_statements
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=SqlAnalyzer(dialect=dialect), log=NullLog()
    )
    result = MigrateResult()

    assert engine.get_executable_sql_statements(_migration(dialect), result) == []
    assert "\\G" in (result.error_message or "")


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_executable_statement_list_of_a_clean_script_is_the_statements(dialect: str) -> None:
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=SqlAnalyzer(dialect=dialect), log=NullLog()
    )
    result = MigrateResult()
    content = "UPDATE t SET a = 1;\nUPDATE t SET a = 2;\n"

    assert engine.get_executable_sql_statements(_migration(dialect, content), result) == [
        "UPDATE t SET a = 1",
        "UPDATE t SET a = 2",
    ]
    assert not result.error_message


@pytest.mark.parametrize("dialect", DIALECTS)
def test_parse_sql_statements_raises_the_refusal(dialect: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="client command"):
        _migration(dialect).parse_sql_statements(dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_migration_parser_does_not_fall_back_to_a_semicolon_split(dialect: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        parse_migration_sql(SqlAnalyzer(dialect=dialect), SCRIPT, NullLog())
    with pytest.raises(UnsupportedMetaCommandError):
        parse_migration_sql(SqlAnalyzer(dialect=dialect), SCRIPT, NullLog(), for_analysis=True)
