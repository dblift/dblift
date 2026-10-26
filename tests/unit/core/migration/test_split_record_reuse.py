"""Execution consumers reuse the authoritative script scan."""

import sys

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer


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
