"""A script carrying the no-transaction directive is refused before any script of the command runs."""

import sqlite3
import sys
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.seams import runtime_checks

DIRECTIVE = "-- dblift:no-transaction\n"
MODES = pytest.mark.parametrize("analysis_mode", ["full", "execution"])


@pytest.fixture(autouse=True)
def _no_extension_checks():
    saved = {key: list(value) for key, value in runtime_checks._CHECKS.items()}
    runtime_checks.clear_checks()
    yield
    runtime_checks.clear_checks()
    runtime_checks._CHECKS.update(saved)


def _client(tmp_path, analysis_mode, **scripts):
    folder = tmp_path / "sql"
    folder.mkdir()
    for name, body in scripts.items():
        (folder / f"{name}.sql").write_text(body)
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=folder, analysis_mode=analysis_mode)


def _tables(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as observer:
        return {
            row[0] for row in observer.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


@MODES
def test_migrate_refuses_before_an_earlier_script_or_callback_runs(tmp_path, analysis_mode):
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        V2__second=DIRECTIVE + "CREATE TABLE second_ran (id INTEGER);",
        beforeMigrate__cb="CREATE TABLE before_cb_ran (id INTEGER);",
        afterMigrateError__cb="CREATE TABLE error_cb_ran (id INTEGER);",
    ) as client:
        result = client.migrate()
    assert not result.success
    assert "V2__second.sql: -- dblift:no-transaction" in result.error_message
    assert "none of its statements were executed" in result.error_message
    assert result.callbacks == []
    assert not {"first_ran", "before_cb_ran", "error_cb_ran", "second_ran"} & _tables(tmp_path)


@MODES
def test_migrate_refuses_a_callback_carrying_the_directive(tmp_path, analysis_mode):
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        beforeMigrate__cb=DIRECTIVE + "CREATE TABLE before_cb_ran (id INTEGER);",
    ) as client:
        result = client.migrate()
    assert not result.success
    assert "beforeMigrate__cb.sql: -- dblift:no-transaction" in result.error_message
    assert not {"first_ran", "before_cb_ran"} & _tables(tmp_path)


@MODES
def test_undo_refuses_before_an_earlier_undo_script_or_callback_runs(tmp_path, analysis_mode):
    with _client(
        tmp_path,
        analysis_mode,
        V1__one="CREATE TABLE one (id INTEGER);",
        V2__two="CREATE TABLE two (id INTEGER);",
    ) as client:
        assert client.migrate().success
        folder = tmp_path / "sql"
        # Undo runs newest first: U2 is the first script, U1 the second.
        (folder / "U2__two.sql").write_text("CREATE TABLE undo_two_ran (id INTEGER);")
        (folder / "U1__one.sql").write_text(DIRECTIVE + "CREATE TABLE undo_one_ran (id INTEGER);")
        (folder / "beforeUndo__cb.sql").write_text("CREATE TABLE before_undo_ran (id INTEGER);")
        (folder / "afterUndoError__cb.sql").write_text("CREATE TABLE undo_error_ran (id INTEGER);")
        result = client.undo(target_version="0")
    assert not result.success
    assert "U1__one.sql: -- dblift:no-transaction" in result.error_message
    assert result.callbacks == []
    assert not {
        "undo_one_ran",
        "undo_two_ran",
        "before_undo_ran",
        "undo_error_ran",
    } & _tables(tmp_path)


@MODES
def test_undo_refuses_a_callback_carrying_the_directive_before_any_undo_script(
    tmp_path, analysis_mode
):
    with _client(
        tmp_path,
        analysis_mode,
        V1__one="CREATE TABLE one (id INTEGER);",
    ) as client:
        assert client.migrate().success
        folder = tmp_path / "sql"
        (folder / "U1__one.sql").write_text("CREATE TABLE undo_one_ran (id INTEGER);")
        (folder / "beforeUndo__cb.sql").write_text("CREATE TABLE before_undo_ran (id INTEGER);")
        (folder / "afterUndo__cb.sql").write_text(
            DIRECTIVE + "CREATE TABLE after_ran (id INTEGER);"
        )
        result = client.undo(target_version="0")
    assert not result.success
    assert "afterUndo__cb.sql: -- dblift:no-transaction" in result.error_message
    assert result.callbacks == []
    assert not {"undo_one_ran", "before_undo_ran", "after_ran"} & _tables(tmp_path)


@MODES
@pytest.mark.parametrize("event", ["beforeMigrate", "beforeEachMigrate", "afterMigrate"])
def test_migrate_dry_run_refuses_a_callback_carrying_the_directive(tmp_path, analysis_mode, event):
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        **{f"{event}__cb": DIRECTIVE + "CREATE TABLE cb_ran (id INTEGER);"},
    ) as client:
        result = client.migrate(dry_run=True)
    assert not result.success
    assert f"{event}__cb.sql: -- dblift:no-transaction" in result.error_message
    assert "none of its statements were executed" in result.error_message
    assert not {"first_ran", "cb_ran"} & _tables(tmp_path)


@MODES
def test_undo_dry_run_refuses_a_callback_carrying_the_directive(tmp_path, analysis_mode):
    with _client(
        tmp_path,
        analysis_mode,
        V1__one="CREATE TABLE one (id INTEGER);",
    ) as client:
        assert client.migrate().success
        folder = tmp_path / "sql"
        (folder / "U1__one.sql").write_text("DROP TABLE one;")
        (folder / "beforeUndo__cb.sql").write_text(
            DIRECTIVE + "CREATE TABLE before_undo_ran (id INTEGER);"
        )
        result = client.undo(target_version="0", dry_run=True)
    assert not result.success
    assert "beforeUndo__cb.sql: -- dblift:no-transaction" in result.error_message
    assert "one" in _tables(tmp_path)
    assert "before_undo_ran" not in _tables(tmp_path)


@MODES
@pytest.mark.parametrize("command", ["validate", "clean"])
def test_validate_and_clean_refuse_a_callback_carrying_the_directive(
    tmp_path, analysis_mode, command
):
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        **{
            f"before{command.title()}__cb": DIRECTIVE + "CREATE TABLE cb_ran (id INTEGER);",
        },
    ) as client:
        assert client.migrate().success
        result = client.validate() if command == "validate" else client.clean(clean_enabled=True)
    assert not result.success
    assert "-- dblift:no-transaction" in result.error_message
    assert "cb_ran" not in _tables(tmp_path)
    if command == "clean":
        assert "first_ran" in _tables(tmp_path)


@MODES
def test_a_run_without_the_directive_probes_nothing_for_the_refusal(
    tmp_path, analysis_mode, monkeypatch
):
    probed_by = []
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        beforeMigrate__cb="CREATE TABLE before_cb_ran (id INTEGER);",
    ) as client:
        provider_type = type(client.provider)
        for name in ("supports_script_session", "is_caller_owned"):
            real = getattr(provider_type, name)

            def spy(self, _real=real):
                probed_by.append(sys._getframe(1).f_code.co_name)
                return _real(self)

            monkeypatch.setattr(provider_type, name, spy)
        result = client.migrate()
    assert result.success, result.error_message
    assert "script_session_refusal" not in probed_by


@MODES
def test_the_callbacks_checked_are_the_callbacks_fired(tmp_path, analysis_mode, monkeypatch):
    original = MigrateCommand._refuse_unsupported_script_sessions

    def refuse_then_add_a_callback(self, scripts):
        original(self, scripts)
        (tmp_path / "sql" / "beforeMigrate__late.sql").write_text(
            "CREATE TABLE late_ran (id INTEGER);"
        )

    monkeypatch.setattr(
        MigrateCommand, "_refuse_unsupported_script_sessions", refuse_then_add_a_callback
    )
    with _client(
        tmp_path,
        analysis_mode,
        V1__first="CREATE TABLE first_ran (id INTEGER);",
        beforeMigrate__cb="CREATE TABLE before_cb_ran (id INTEGER);",
    ) as client:
        result = client.migrate()
    assert result.success, result.error_message
    assert {"first_ran", "before_cb_ran"} <= _tables(tmp_path)
    assert "late_ran" not in _tables(tmp_path)


def _command_with_engine(engine):
    command = BaseCommand.__new__(BaseCommand)
    command.execution_engine = engine
    return command


def test_a_string_refusal_is_raised_with_its_text():
    engine = MagicMock()
    engine.script_session_refusal.return_value = "V2.sql: refused"
    with pytest.raises(runtime_checks.SqlPreflightError, match="V2.sql: refused"):
        _command_with_engine(engine)._refuse_unsupported_script_sessions([object()])


def test_a_bare_mock_engine_refuses_nothing():
    _command_with_engine(MagicMock())._refuse_unsupported_script_sessions([object()])
