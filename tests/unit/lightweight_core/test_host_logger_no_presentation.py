"""A host Log receives operation messages without activating presentation."""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit.lightweight_core._support import run_python


def test_default_operations_do_not_construct_a_migration_ui(tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    from dblift.api import DBLiftClient

    (tmp_path / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);")
    (tmp_path / "U1__t.sql").write_text("DROP TABLE t;")
    engine = create_engine("sqlite:///:memory:")
    with patch("dblift.core.migration.executor.migration_executor.MigrationUI") as ui:
        with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path) as client:
            assert client.migrate().success
            assert client.info().success
            assert client.undo().success
        ui.assert_not_called()
    engine.dispose()


_IMPORT_GUARD = """
import importlib.abc
import sys

presentation_attempts = []
class PresentationImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in (
            'rich', 'jinja2', 'dblift.core.logger.formatters',
            'dblift.core.migration.ui.rich_progress',
            'dblift.core.migration.ui.table_renderer',
        )):
            presentation_attempts.append(fullname)
            if BLOCK_PRESENTATION:
                raise ModuleNotFoundError('presentation blocked: ' + fullname, name=fullname)
sys.meta_path.insert(0, PresentationImports())
"""

_HOST_OPERATIONS = """
import contextlib
import io
from pathlib import Path

stdout, stderr = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    from sqlalchemy import create_engine
    from dblift.api import DBLiftClient
    from dblift.core.logger import Log, LogLevel

    class CollectingHostLog(Log):
        def __init__(self):
            super().__init__('host')
            self.events = []

        def _log_direct(self, level, message):
            self.events.append((level, message))

    migrations = Path('migrations')
    migrations.mkdir()
    (migrations / 'V1__create_t.sql').write_text(
        'CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (7); SELECT id FROM t;'
    )
    (migrations / 'U1__create_t.sql').write_text('DROP TABLE t;')
    (migrations / 'beforeMigrate__check.sql').write_text('SELECT 11 AS callback_value;')
    engine = create_engine('sqlite:///app.db')
    log = CollectingHostLog()
    events = []
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=log) as client:
        assert client.logger is log
        assert client.analysis_mode == 'execution'
        client.events.on('*', lambda event: events.append(event.event_type.value))
        migrated = client.migrate(show_query_results=True)
        assert migrated.success, migrated.error_message
        assert migrated.migrations_applied == ['1']
        assert migrated.end_time is not None
        assert [(row.script, row.status) for row in migrated.migrations] == [
            ('V1__create_t.sql', 'SUCCESS')
        ]
        query_rows = [result_set['rows'] for query in migrated.query_results for result_set in query.results]
        assert [[7]] in query_rows, query_rows
        assert [[11]] in query_rows, query_rows
        assert [(callback.file, callback.status) for callback in migrated.callbacks] == [
            ('beforeMigrate__check.sql', 'OK')
        ]
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT id FROM t').fetchall() == [(7,)]
            assert connection.exec_driver_sql(
                'SELECT script, success FROM dblift_schema_history ORDER BY installed_rank'
            ).fetchall() == [('V1__create_t.sql', 1)]
        info = client.info()
        assert info.success, info.error_message
        assert info.current_schema_version == '1'
        assert [(row.script, row.status) for row in info.migrations] == [
            ('V1__create_t.sql', 'SUCCESS')
        ]
        undone = client.undo()
        assert undone.success, undone.error_message
        assert undone.undone_count == 1
        assert [(row.script, row.status) for row in undone.undone_migrations] == [
            ('U1__create_t.sql', 'UNDONE')
        ]
        after = client.info()
        assert after.success, after.error_message
        assert after.current_schema_version is None
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='t'"
        ).fetchall() == []
        assert connection.exec_driver_sql(
            'SELECT script, success FROM dblift_schema_history ORDER BY installed_rank'
        ).fetchall() == [('V1__create_t.sql', 1), ('U1__create_t.sql', 1)]
    engine.dispose()
    assert events.count('migration.script.completed') == 2, events
    assert events.count('migration.completed') == 1, events
    assert events.count('undo.completed') == 1, events
    messages = [message for _, message in log.events]
    assert 'Successfully applied migration V1__create_t.sql' in messages, messages
    assert 'Successfully undone migration V1__create_t.sql' in messages, messages
    assert 'Query executed successfully, 1 rows returned' in messages, messages
    assert any(message.startswith('Statement executed successfully') for message in messages), messages

# These assertions run after the complete SQLite migrate/info/undo round trip.
assert stdout.getvalue() == '', 'host operation wrote presentation to stdout: ' + stdout.getvalue()
assert stderr.getvalue() == '', 'host operation wrote presentation to stderr: ' + stderr.getvalue()
assert not any('│' in message or '╭' in message for message in messages), messages
assert presentation_attempts == [], presentation_attempts
"""


@pytest.mark.parametrize("block_presentation", [False, True], ids=["installed", "blocked"])
def test_host_log_migrate_info_undo_without_presentation(
    tmp_path: Path, block_presentation: bool
) -> None:
    process = run_python(
        f"BLOCK_PRESENTATION = {block_presentation!r}\n" + _IMPORT_GUARD + _HOST_OPERATIONS,
        cwd=tmp_path,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == process.stderr == ""


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_default_clients_complete_silently_without_presentation(
    tmp_path: Path, asynchronous: bool
) -> None:
    source = """
import asyncio
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.api.async_client import AsyncDBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
migrations.mkdir()
(migrations / 'V1__create_t.sql').write_text('CREATE TABLE t (id INTEGER);')
(migrations / 'U1__create_t.sql').write_text('DROP TABLE t;')
engine = create_engine('sqlite:///app.db')

async def run_async():
    async with AsyncDBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations) as client:
        assert client.analysis_mode == 'execution'
        assert (await client.migrate()).success
        assert (await client.info()).current_schema_version == '1'
        assert (await client.undo()).success

if ASYNCHRONOUS:
    asyncio.run(run_async())
else:
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations) as client:
        assert isinstance(client.logger, NullLog)
        assert client.analysis_mode == 'execution'
        assert client.migrate().success
        assert client.info().current_schema_version == '1'
        assert client.undo().success
with engine.connect() as connection:
    assert connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='t'").all() == []
    assert connection.exec_driver_sql(
        'SELECT script, success FROM dblift_schema_history ORDER BY installed_rank'
    ).fetchall() == [('V1__create_t.sql', 1), ('U1__create_t.sql', 1)]
engine.dispose()
assert not Path('logs').exists()
assert presentation_attempts == [], presentation_attempts
"""
    process = run_python(
        f"BLOCK_PRESENTATION = True\nASYNCHRONOUS = {asynchronous!r}\n" + _IMPORT_GUARD + source,
        cwd=tmp_path,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == process.stderr == ""


def test_host_log_keeps_failure_details_and_warning_levels(tmp_path: Path, capsys) -> None:
    from sqlalchemy import create_engine

    from dblift.api import DBLiftClient
    from dblift.core.logger import Log, LogLevel

    class CollectingHostLog(Log):
        def __init__(self):
            super().__init__("host")
            self.events = []

        def _log_direct(self, level, message):
            self.events.append((level, message))

    (tmp_path / "V1__bad.sql").write_text("INSERT INTO missing_table VALUES (1);")
    engine = create_engine("sqlite:///:memory:")
    log = CollectingHostLog()
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=log) as client:
        failed = client.migrate()
        assert failed.success is False
        assert "no such table: missing_table" in failed.error_message
        assert failed.failed_history_persisted is True
        (tmp_path / "V2__first.sql").write_text("SELECT 1;")
        (tmp_path / "V2__second.sql").write_text("SELECT 2;")
        assert client.info().success
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT script, success FROM dblift_schema_history"
        ).fetchall() == [("V1__bad.sql", 0)]
    engine.dispose()

    assert any(
        level == LogLevel.ERROR and "no such table: missing_table" in message
        for level, message in log.events
    ), log.events
    assert any(
        level == LogLevel.WARN and "Duplicate version 2:" in message
        for level, message in log.events
    ), log.events
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("sink_kind", ["console", "file", "wrapped", "host"])
def test_nested_multilog_selects_only_builtin_presentation(
    tmp_path: Path, sink_kind: str, capsys
) -> None:
    from rich.progress import Progress
    from sqlalchemy import create_engine

    from dblift.api import DBLiftClient
    from dblift.core.logger import ConsoleLog, DbliftLogger, FileLog, Log, MultiLog
    from dblift.core.logger.console import render_records_table

    class CollectingHostLog(Log):
        def __init__(self):
            super().__init__("host")
            self.events = []

        def _log_direct(self, level, message):
            self.events.append((level, message))

    sink = {
        "console": lambda: ConsoleLog("nested"),
        "file": lambda: FileLog("nested", tmp_path / "logs"),
        "wrapped": lambda: DbliftLogger("nested", logfile_dir=tmp_path / "logs"),
        "host": CollectingHostLog,
    }[sink_kind]()
    log = MultiLog([MultiLog([sink])])
    (tmp_path / "V1__query.sql").write_text("CREATE TABLE t (id INTEGER); SELECT 7 AS value;")
    engine = create_engine("sqlite:///:memory:")
    completed = []
    original_exit = Progress.__exit__

    def record_exit(progress, *args):
        completed.extend((task.total, task.completed) for task in progress.tasks)
        return original_exit(progress, *args)

    with (
        patch(
            "dblift.core.migration.executor.execution_engine.render_records_table",
            wraps=render_records_table,
        ) as renderer,
        patch.object(Progress, "__exit__", record_exit),
    ):
        with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=log) as client:
            result = client.migrate(show_query_results=True)
            assert result.success, result.error_message
            assert result.query_results[0].results[0]["rows"] == [[7]]
        assert renderer.call_count == (0 if sink_kind == "host" else 1)
    assert completed == ([] if sink_kind == "host" else [(1, 1)])
    engine.dispose()
    if sink_kind == "host":
        captured = capsys.readouterr()
        assert captured.out == captured.err == ""
        assert any("Successfully applied migration" in message for _, message in sink.events)
    if hasattr(sink, "close"):
        sink.close()
