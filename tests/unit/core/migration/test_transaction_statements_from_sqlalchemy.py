"""SQLite and DuckDB: transaction statements in a migration, through ``DBLiftClient.from_sqlalchemy``.

The external-connection path runs on SQLAlchemy's own connection and transaction, unlike the CLI
(see the integration module of the same name for the subprocess path). Both read the outcomes from
``tests.support.transaction_scenarios`` and assert database state after a real ``migrate()``.
"""

import logging

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from tests.support.transaction_scenarios import SCENARIOS, SCRIPT, cases, database_url, read_state

pytest.importorskip("duckdb_engine")


def _migrate(engine_name, tmp_path, script):
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / SCRIPT).write_text(script)
    engine = create_engine(database_url(engine_name, tmp_path))
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        return client.migrate()
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize("engine_name, name", cases())
def test_scenario(engine_name, name, tmp_path, caplog, capfd):
    scenario = SCENARIOS[name]
    with caplog.at_level(logging.INFO):
        result = _migrate(engine_name, tmp_path, scenario.script)
    output = caplog.text + "".join(capfd.readouterr())

    assert result.success is (scenario.status == "applied")
    assert read_state(engine_name, tmp_path) == (scenario.tables, scenario.expected_history())
    if scenario.message:
        assert scenario.message in (result.error_message or "")
    if scenario.status == "refused":
        assert SCRIPT in result.error_message
        assert "Failed to parse SQL" not in result.error_message


@pytest.mark.parametrize("engine_name", ["sqlite", "duckdb"])
def test_envelope_is_dropped_with_a_warning(engine_name, tmp_path, caplog, capfd):
    with caplog.at_level(logging.INFO):
        _migrate(engine_name, tmp_path, SCENARIOS["envelope"].script)
    output = caplog.text + "".join(capfd.readouterr())

    assert "Dropped BEGIN and COMMIT from V1__x.sql" in output
    assert "dblift runs the migration in one transaction of its own" in output


def test_duckdb_bare_commit_never_reaches_the_driver_shim(tmp_path, monkeypatch):
    """#1529: ``duckdb_engine`` turns a bare ``commit`` into ``connection.commit()`` and swallows the error."""
    import duckdb_engine

    seen = []
    original = duckdb_engine.CursorWrapper.execute

    def spy(self, statement, parameters=None, context=None):
        seen.append(statement)
        return original(self, statement, parameters, context)

    monkeypatch.setattr(duckdb_engine.CursorWrapper, "execute", spy)
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / SCRIPT).write_text("COMMIT;\n")
    engine = create_engine(database_url("duckdb", tmp_path))
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        result = client.migrate()
    finally:
        client.close()
        engine.dispose()

    assert not result.success
    assert not [s for s in seen if s.strip().rstrip(";").upper() == "COMMIT"]


@pytest.mark.parametrize("engine_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize(
    "analysis_mode, applied_before_refusal",
    [("execution", []), ("full", ["V1__a.sql", "V2__b.sql"])],
)
def test_a_refused_later_script_in_a_run(
    engine_name, analysis_mode, applied_before_refusal, tmp_path
):
    """Execution mode preflights every script before the first runs; full mode meets it at its turn."""
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE a (a INT);")
    (migrations / "V2__b.sql").write_text("CREATE TABLE b (a INT);")
    (migrations / "V3__c.sql").write_text("CREATE TABLE c (a INT);\nCOMMIT;\n")
    engine = create_engine(database_url(engine_name, tmp_path))
    client = DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=str(migrations), analysis_mode=analysis_mode
    )
    try:
        result = client.migrate()
    finally:
        client.close()
        engine.dispose()

    tables, history = read_state(engine_name, tmp_path)
    assert not result.success
    assert "V3__c.sql, line 2: COMMIT manages the transaction" in result.error_message
    assert [script for script, _ in history] == applied_before_refusal
    assert sorted(tables) == ["a", "b"][: len(applied_before_refusal)]
