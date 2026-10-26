"""Execution consumers reuse the authoritative script scan."""

import sys

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.exceptions import TransactionStatementError
from dblift.core.logger import NullLog
from dblift.core.migration.sql.execution_statement import (
    PreparedStatements,
    classify_execution_statement,
    neutralise_transaction_statements,
)
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.statement import execution_strings


@pytest.mark.parametrize("analysis_mode", ["full", "execution"])
def test_migrate_does_not_rescan_each_statement_for_execution_policy(tmp_path, analysis_mode):
    count = 12
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__seed.sql").write_text(
        "CREATE TABLE t (id INTEGER);\n"
        + "".join(f"INSERT INTO t VALUES ({i}) /* tail */;\n" for i in range(count))
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode=analysis_mode
    )
    statement_scans = []

    def count_policy_scans(frame, event, _arg):
        if event != "call" or frame.f_code is not BaseTokenizer.__init__.__code__:
            return
        sql = frame.f_locals.get("sql", "")
        if not sql.lstrip().startswith("INSERT INTO t VALUES"):
            return
        caller = frame.f_back
        while caller is not None:
            if caller.f_code.co_filename.endswith("/execution_statement.py"):
                statement_scans.append(sql)
                return
            caller = caller.f_back

    try:
        sys.setprofile(count_policy_scans)
        try:
            result = client.migrate()
        finally:
            sys.setprofile(None)
        assert result.success
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM t")).scalar_one() == count
    finally:
        client.close()
        engine.dispose()

    assert statement_scans == []


def test_record_policy_view_blanks_comments_but_preserves_quoted_text():
    sql = "SELECT '/* stays */'; INSERT /* ignored */ INTO t VALUES (1);"
    records = StatementSplitter("sqlite").split(sql)

    assert records[0].policy_text == "SELECT '/* stays */'"
    assert records[1].policy_text.split() == ["INSERT", "INTO", "t", "VALUES", "(1)"]


def test_repeated_batch_policy_views_stay_aligned_with_execution_strings():
    sql = "SELECT 1;\nGO 0\nCREATE /* flush */ INDEX ix ON t(a);\nGO 2"
    records = StatementSplitter("sqlserver").split(sql)
    sent = execution_strings(records)
    prepared = neutralise_transaction_statements(
        sent, dialect="sqlserver", log=NullLog(), content=sql, records=records
    )

    assert isinstance(prepared, PreparedStatements)
    assert len(prepared) == len(prepared.policy_texts) == 2
    assert all(text.split()[:2] == ["CREATE", "INDEX"] for text in prepared.policy_texts)


def test_transaction_policy_uses_comment_blank_from_original_scan():
    sql = "CREATE /* flush */ INDEX CONCURRENTLY ix ON t(a);"
    records = StatementSplitter("postgresql").split(sql)
    sent = execution_strings(records)
    prepared = neutralise_transaction_statements(
        sent, dialect="postgresql", log=NullLog(), content=sql, records=records
    )

    assert not classify_execution_statement(
        prepared[0], dialect="postgresql", policy_text=prepared.policy_texts[0]
    ).can_execute_in_transaction


def test_cached_split_carries_policy_views_for_copy_and_following_sql():
    sql = "COPY t FROM STDIN;\n-- raw value\n\\.\nINSERT /* comment */ INTO t VALUES (1);"
    splitter = StatementSplitter("postgresql")
    sent = splitter.split_statements(sql)
    records = splitter.last_split(sql)
    prepared = neutralise_transaction_statements(
        sent, dialect="postgresql", log=NullLog(), content=sql, records=records
    )

    assert len(prepared) == len(prepared.policy_texts) == 2
    assert "-- raw value" in prepared.policy_texts[0]
    assert "comment" not in prepared.policy_texts[1]


def test_multi_statement_batch_keeps_constituent_classification():
    records = StatementSplitter("sqlserver").split(
        "SELECT 1; BACKUP DATABASE db TO DISK = 'x';\nGO"
    )

    assert len(records) == 1
    assert len(records[0].analysis_statements) == 2
    assert records[0].policy_text is None


@pytest.mark.parametrize("statement", ["COMMIT", "BEGIN TRANSACTION"])
def test_stale_policy_records_cannot_hide_transaction_control(statement):
    records = StatementSplitter("sqlite").split("SELECT 1;")

    with pytest.raises(TransactionStatementError):
        neutralise_transaction_statements(
            [statement],
            dialect="sqlite",
            log=NullLog(),
            content=statement,
            records=records,
        )
