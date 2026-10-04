"""The explicit null logger runs migrations without presentation dependencies."""

from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger import DbliftLogger, LogFormat, NullLog
from dblift.core.logger.results import MigrateResult, OperationResult, ValidateResult
from dblift.core.migration.commands.base_command import BaseCommand
from tests.unit.lightweight_core._support import run_python


def test_sqlite_commands_without_rich_or_jinja2(tmp_path: Path) -> None:
    result = run_python(
        """
from pathlib import Path
from sqlalchemy import create_engine, text
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

migrations = Path('migrations')
migrations.mkdir()
(migrations / 'V1__create_t.sql').write_text(
    'CREATE TABLE t (id INTEGER); INSERT INTO t (id) VALUES (7); SELECT id FROM t;'
)
(migrations / 'U1__create_t.sql').write_text('DROP TABLE t;')
engine = create_engine('sqlite:///:memory:')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog()) as client:
    migrated = client.migrate(show_query_results=True)
    assert migrated.success
    assert migrated.query_results[0].results[0]['rows'] == [[7]]
    with engine.connect() as connection:
        assert connection.execute(text('SELECT COUNT(*) FROM t')).scalar_one() == 1
    assert client.info().success
    assert client.validate().success
    assert client.undo().success
with engine.connect() as connection:
    assert connection.execute(text("SELECT name FROM sqlite_master WHERE name = 't'")).all() == []
    assert connection.execute(text('SELECT 1')).scalar_one() == 1
assert sorted(str(p) for p in Path('.').rglob('*') if p.is_file()) == [
    'migrations/U1__create_t.sql', 'migrations/V1__create_t.sql'
]
engine.dispose()
""",
        blocked=("rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_failed_sql_stops_following_script_and_keeps_external_engine(tmp_path: Path) -> None:
    (tmp_path / "V1__ok.sql").write_text("CREATE TABLE t (id INTEGER);")
    (tmp_path / "V2__bad.sql").write_text("INSERT INTO missing_table VALUES (1);")
    (tmp_path / "V3__never.sql").write_text("CREATE TABLE never_run (id INTEGER);")
    engine = create_engine("sqlite:///:memory:")

    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=NullLog()) as client:
        events: list[str] = []
        client.events.on("*", lambda event: events.append(event.event_type.value))
        result = client.migrate()
        assert isinstance(result, MigrateResult)
        assert not result.success
        assert "no such table: missing_table" in (result.error_message or "")
        assert result.failed_history_persisted is True
        assert [(migration.script, migration.status) for migration in result.migrations] == [
            ("V1__ok.sql", "SUCCESS"),
            ("V2__bad.sql", "FAILED"),
        ]
        assert result.migrations[-1].error == "no such table: missing_table"
        assert result.journal is not None
        failed_statements = [
            entry
            for entry in result.journal.entries
            if entry.entry_type.value == "STATEMENT_FAILED"
        ]
        assert len(failed_statements) == 1
        assert failed_statements[0].migration_id == "V2__bad.sql"
        assert failed_statements[0].statement == "INSERT INTO missing_table VALUES (1);"
        assert failed_statements[0].error_message == "no such table: missing_table"
        assert events == [
            "migration.started",
            "migration.script.started",
            "migration.script.completed",
            "migration.script.started",
            "migration.script.failed",
            "migration.failed",
        ]

    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT script, success FROM dblift_schema_history ORDER BY installed_rank"
        ).fetchall() == [("V1__ok.sql", 1), ("V2__bad.sql", 0)]
        assert (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE name='never_run'"
            ).fetchall()
            == []
        )
        assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    engine.dispose()


def test_silent_checksum_drift_keeps_validation_details(tmp_path: Path) -> None:
    script = tmp_path / "V1__t.sql"
    script.write_text("CREATE TABLE t (id INTEGER);")
    engine = create_engine("sqlite:///:memory:")

    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=NullLog()) as client:
        assert client.migrate().success
        script.write_text("CREATE TABLE t (id INTEGER);\n-- changed after apply\n")
        result = client.validate()

    assert isinstance(result, ValidateResult)
    assert result.success is False
    assert "modified since it was applied" in (result.error_message or "")
    assert any("V1__t.sql" in issue for issue in result.issues)
    assert [(migration.script, migration.status) for migration in result.failed_migrations] == [
        ("V1__t.sql", "FAILED")
    ]
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM t").scalar_one() == 0
    engine.dispose()


def test_silent_callback_failure_keeps_callback_record_and_stops_migration(
    tmp_path: Path,
) -> None:
    (tmp_path / "beforeEach__gate.sql").write_text("SELECT * FROM missing_callback_table;")
    (tmp_path / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);")
    engine = create_engine("sqlite:///:memory:")

    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=NullLog()) as client:
        result = client.migrate()

    assert isinstance(result, MigrateResult)
    assert result.success is False
    assert "missing_callback_table" in (result.error_message or "")
    assert [(record.phase, record.status, record.file) for record in result.callbacks] == [
        ("beforeEach", "FAILED", "beforeEach__gate.sql")
    ]
    assert result.migrations == []
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='t'").fetchall()
            == []
        )
    engine.dispose()


def test_silent_text_silent_clients_do_not_share_output_or_events(tmp_path: Path, capsys) -> None:
    captures = []
    event_lists = []
    for index, silent in enumerate((True, False, True)):
        migrations = tmp_path / f"migrations-{index}"
        migrations.mkdir()
        (migrations / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);")
        (migrations / "U1__t.sql").write_text("DROP TABLE t;")
        engine = create_engine("sqlite:///:memory:")
        logger = (
            NullLog()
            if silent
            else DbliftLogger(
                f"run-{index}", format=LogFormat.TEXT, logfile_dir=tmp_path / "text-logs"
            )
        )
        events: list[str] = []
        capsys.readouterr()
        with DBLiftClient.from_sqlalchemy(
            engine, migrations_dir=migrations, logger=logger
        ) as client:
            client.events.on("*", lambda event: events.append(event.event_type.value))
            assert client.migrate().success
            assert client.info().success
            assert client.validate().success
            assert client.undo().success
        if not silent:
            logger.close()
        captures.append(capsys.readouterr())
        event_lists.append(events)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        engine.dispose()

    assert captures[0].out == captures[0].err == ""
    assert captures[1].out or captures[1].err
    assert captures[2].out == captures[2].err == ""
    for events in event_lists:
        assert events.count("migration.started") == 1
        assert events.count("migration.completed") == 1
        assert events.count("undo.started") == 1
        assert events.count("undo.completed") == 1


def test_failed_sql_and_checksum_are_silent_without_rendering_packages(tmp_path: Path) -> None:
    result = run_python(
        """
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

failed = Path('failed')
failed.mkdir()
(failed / 'V1__ok.sql').write_text('CREATE TABLE t (id INTEGER);')
(failed / 'V2__bad.sql').write_text('INSERT INTO missing_table VALUES (1);')
engine = create_engine('sqlite:///:memory:')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=failed, logger=NullLog()) as client:
    migration = client.migrate()
    assert not migration.success
    assert 'missing_table' in migration.error_message
with engine.connect() as connection:
    assert connection.exec_driver_sql('SELECT COUNT(*) FROM t').scalar_one() == 0
engine.dispose()

drift = Path('drift')
drift.mkdir()
script = drift / 'V1__t.sql'
script.write_text('CREATE TABLE t (id INTEGER);')
engine = create_engine('sqlite:///:memory:')
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=drift, logger=NullLog()) as client:
    assert client.migrate().success
    script.write_text('CREATE TABLE t (id INTEGER);\\n-- changed\\n')
    validation = client.validate()
    assert not validation.success
    assert 'modified since it was applied' in validation.error_message
engine.dispose()
assert sorted(str(p) for p in Path('.').rglob('*') if p.is_file()) == [
    'drift/V1__t.sql', 'failed/V1__ok.sql', 'failed/V2__bad.sql'
]
""",
        blocked=("rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_async_exception_cleanup_without_rendering_packages(tmp_path: Path) -> None:
    result = run_python(
        """
import asyncio
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api.async_client import AsyncDBLiftClient
from dblift.core.logger import NullLog

async def run():
    migrations = Path('migrations')
    migrations.mkdir()
    (migrations / 'V1__t.sql').write_text('CREATE TABLE t (id INTEGER);')
    engine = create_engine('sqlite:///async.db')
    try:
        async with AsyncDBLiftClient.from_sqlalchemy(
            engine, migrations_dir=migrations, logger=NullLog()
        ) as client:
            assert (await client.migrate()).success
            raise RuntimeError('host failure')
    except RuntimeError as error:
        assert str(error) == 'host failure'
    else:
        raise AssertionError('context exception was suppressed')
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM t').scalar_one() == 0
    engine.dispose()
    assert list(Path('.').glob('*.html')) == []
    assert list(Path('.').glob('*.json')) == []

asyncio.run(run())
""",
        blocked=("rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_null_logger_finalizes_failed_result_without_rendering() -> None:
    command = BaseCommand.__new__(BaseCommand)
    command.log = NullLog()
    result = OperationResult(success=False, error_message="migration failed")

    with (
        patch.object(command, "_format_command_footer", side_effect=AssertionError("rendered")),
        patch.object(
            command, "_resolve_current_schema_version", side_effect=AssertionError("footer read")
        ),
    ):
        command._log_command_completion("migrate", result)

    assert result.end_time is not None
    assert result.success is False
    assert result.error_message == "migration failed"


def test_header_and_footer_formatters_keep_subclass_panel_dispatch() -> None:
    from rich.panel import Panel

    class CustomCommand(BaseCommand):
        def _build_command_header_panel(self, *args, **kwargs):
            return Panel("custom header")

        def _build_footer_panel(self, *args, **kwargs):
            return Panel("custom footer")

    command = CustomCommand.__new__(CustomCommand)
    assert "custom header" in command._format_command_header("info", [])
    assert "custom footer" in command._format_command_footer("info", True, "1 ms")
