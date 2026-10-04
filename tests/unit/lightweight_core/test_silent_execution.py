"""The explicit null logger runs migrations without presentation dependencies."""

from pathlib import Path
from unittest.mock import patch

from dblift.core.logger import NullLog
from dblift.core.logger.results import OperationResult
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
