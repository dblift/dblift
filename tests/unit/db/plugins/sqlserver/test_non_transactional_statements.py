"""SQL Server runs these statements in autocommit: it refuses them inside a user transaction (docs/sql-parsing/sqlserver.md section 8)."""

import pytest

from dblift.core.migration.sql.execution_statement import classify_execution_statement


def _can_run_in_a_transaction(sql: str) -> bool:
    return classify_execution_statement(sql, dialect="sqlserver").can_execute_in_transaction


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FULLTEXT CATALOG ft",
        "ALTER FULLTEXT CATALOG ft REBUILD",
        "DROP FULLTEXT CATALOG ft",
        "CREATE FULLTEXT INDEX ON t (c) KEY INDEX pk_t",
        "ALTER FULLTEXT INDEX ON t DISABLE",
        "DROP FULLTEXT INDEX ON t",
        "CREATE DATABASE d",
        "ALTER DATABASE d SET RECOVERY SIMPLE",
        "ALTER DATABASE d MODIFY FILE (NAME = d, MAXSIZE = UNLIMITED)",
        "ALTER DATABASE SCOPED CONFIGURATION SET MAXDOP = 1",
        "DROP DATABASE d",
        "BACKUP DATABASE d TO DISK = '/tmp/d.bak'",
        "RESTORE DATABASE d FROM DISK = '/tmp/d.bak'",
        "RESTORE VERIFYONLY FROM DISK = '/tmp/d.bak'",
        "BACKUP LOG d TO DISK = '/tmp/d.trn'",
        "RESTORE LOG d FROM DISK = '/tmp/d.trn'",
        "RECONFIGURE",
        "RECONFIGURE WITH OVERRIDE",
        "KILL 53",
        "KILL STATS JOB 1",
        "KILL '00000000-0000-0000-0000-000000000000'",
        "KILL QUERY NOTIFICATION SUBSCRIPTION ALL",
        "ALTER SERVER AUDIT a WITH (STATE = OFF)",
        "ALTER SERVER CONFIGURATION SET PROCESS AFFINITY CPU = AUTO",
        "DROP FULLTEXT STOPLIST sl",
        "DROP SEARCH PROPERTY LIST spl",
        "-- a note\ncreate   database d",
        "/* a */ ALTER\n  DATABASE d SET READ_ONLY",
    ],
)
def test_a_statement_sql_server_refuses_in_a_user_transaction_runs_in_autocommit(sql):
    assert _can_run_in_a_transaction(sql) is False


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (id INT)",
        "ALTER TABLE t ADD c INT",
        "ALTER INDEX i ON t REBUILD",
        "DROP TABLE t",
        "CREATE INDEX i ON t (c)",
        "SELECT 'CREATE DATABASE d'",
        "INSERT INTO backup_log VALUES (1)",
        "EXEC sp_backup_check",
        "SELECT * FROM database_list",
        "RESTORE HEADERONLY FROM DISK = '/tmp/d.bak'",
        "RESTORE FILELISTONLY FROM DISK = '/tmp/d.bak'",
        "RESTORE LABELONLY FROM DISK = '/tmp/d.bak'",
        "BACKUP MASTER KEY TO FILE = '/tmp/mk' ENCRYPTION BY PASSWORD = 'x'",
        "CREATE DATABASE SCOPED CREDENTIAL c WITH IDENTITY = 'x', SECRET = 'y'",
        "ALTER DATABASE SCOPED CREDENTIAL c WITH IDENTITY = 'x', SECRET = 'z'",
        "DROP DATABASE SCOPED CREDENTIAL c",
        "CREATE DATABASE ENCRYPTION KEY WITH ALGORITHM = AES_256 ENCRYPTION BY SERVER CERTIFICATE k",
        "CREATE DATABASE AUDIT SPECIFICATION s FOR SERVER AUDIT a",
    ],
)
def test_other_statements_stay_transactional(sql):
    assert _can_run_in_a_transaction(sql) is True


@pytest.mark.parametrize(
    "batch",
    [
        "CREATE TABLE t (id INT);\nCREATE FULLTEXT INDEX ON t (c) KEY INDEX pk_t",
        "SET NOCOUNT ON;\nALTER DATABASE d SET RECOVERY SIMPLE;\nSELECT 1",
        "SELECT 1;\n-- note\nRECONFIGURE",
    ],
)
def test_a_batch_is_not_transactional_when_any_of_its_statements_is(batch):
    assert _can_run_in_a_transaction(batch) is False


@pytest.mark.parametrize(
    "batch",
    [
        "CREATE TABLE t (id INT);\nINSERT INTO t VALUES (1)",
        "SELECT 'x; CREATE DATABASE d' AS s;\nSELECT 2",
        "SELECT 1 /* ; RECONFIGURE */",
    ],
)
def test_a_statement_name_inside_a_literal_or_comment_does_not_flag_the_batch(batch):
    assert _can_run_in_a_transaction(batch) is True


def test_other_dialects_are_classified_by_the_first_keywords_only():
    result = classify_execution_statement(
        "CREATE TABLE t (id INT); DROP DATABASE d", dialect="postgresql"
    )
    assert result.can_execute_in_transaction is True
