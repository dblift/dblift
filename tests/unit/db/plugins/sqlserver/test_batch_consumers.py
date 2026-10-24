"""What the callers of the execution split see for SQL Server: batches, not ``;`` statements."""

from unittest.mock import MagicMock

from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.sql.statement_reader import StatementReader
from tests.unit._migration_factory import make_migration

SCRIPT = (
    "CREATE TABLE a (id INT);\n"
    "INSERT INTO a VALUES (1);\n"
    "GO\n"
    "INSERT INTO a VALUES (2)\n"
    "GO 2\n"
    "SELECT 1 AS go;\n"
)
BATCHES = [
    "CREATE TABLE a (id INT);\nINSERT INTO a VALUES (1);",
    "INSERT INTO a VALUES (2)",
    "INSERT INTO a VALUES (2)",
    "SELECT 1 AS go;",
]


def _migration(content=SCRIPT):
    return make_migration(
        script_name="V1__batches.sql",
        content=content,
        version="1",
        description="batches",
        type=MigrationType.SQL,
        dialect="sqlserver",
    )


def test_the_executable_statement_list_is_the_batches_with_go_n_copies():
    # dry-run and plan listings call get_executable_sql_statements: the list is what a run sends
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=StatementReader(dialect="sqlserver"), log=NullLog()
    )
    result = MigrateResult()

    assert engine.get_executable_sql_statements(_migration(), result) == BATCHES
    assert result.success is not False


def test_a_batch_with_a_non_transactional_statement_after_the_first_is_not_listed_as_an_error():
    # the listing classifies each batch as a whole: CREATE TABLE then CREATE FULLTEXT INDEX in one
    # batch is one autocommit batch, not a "mixed" migration
    content = "CREATE TABLE a (id INT);\nCREATE FULLTEXT INDEX ON a (id) KEY INDEX pk_a;\nGO\n"
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=StatementReader(dialect="sqlserver"), log=NullLog()
    )
    result = MigrateResult()

    listed = engine.get_executable_sql_statements(_migration(content), result)

    assert listed == [content.rsplit("GO", 1)[0].strip()]
    assert not result.error_message


def test_parse_sql_statements_returns_batches_and_caches_only_canonical_content():
    migration = _migration()

    assert migration.parse_sql_statements("sqlserver") == BATCHES
    assert migration._sql_statements == BATCHES

    other = migration.parse_sql_statements("sqlserver", content_override="SELECT 9\nGO 3\n")
    assert other == ["SELECT 9"] * 3
    assert migration._sql_statements == BATCHES  # the override did not poison the cache


def test_a_script_the_splitter_refuses_is_not_listed():
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=StatementReader(dialect="sqlserver"), log=NullLog()
    )
    result = MigrateResult()

    assert engine.get_executable_sql_statements(_migration("SELECT 1\nGO foo\n"), result) == []
    assert result.error_message
