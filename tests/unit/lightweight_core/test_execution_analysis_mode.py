"""The explicit execution mode runs migrations without optional analysis packages."""

import json

import pytest

from tests.unit.lightweight_core._support import run_python


@pytest.mark.parametrize("mode", ["full", "execution"])
def test_inprocess_mode_preserves_selected_migration_and_undo_semantics(tmp_path, mode):
    """Coverage-visible execution retains selected SQL, callbacks, and journal events."""
    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog
    from dblift.core.migration.journals.migration_journal import EntryType

    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "beforeMigrate__audit.sql").write_text(
        "CREATE TABLE IF NOT EXISTS audit (event TEXT);"
    )
    (migrations / "beforeEach__audit.py").write_text(
        "def migrate(context):\n    context.execute(\"INSERT INTO audit VALUES ('before')\")\n"
    )
    (migrations / "V1__create.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "V2__insert.sql").write_text(
        "WITH seed AS (SELECT 7 AS id) INSERT INTO t SELECT id FROM seed;"
    )
    (migrations / "U2__insert.sql").write_text("DELETE FROM t WHERE id = 7;")
    (migrations / "U1__create.sql").write_text("DROP VIEW IF EXISTS report; DROP TABLE t;")
    (migrations / "R__view.sql").write_text("CREATE VIEW report AS SELECT id FROM t;")
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"}}
    )
    with DBLiftClient.from_config(
        config, migrations_dir=migrations, logger=NullLog(), analysis_mode=mode
    ) as client:
        for preview in (client.info(), client.migrate(dry_run=True)):
            pending = next(m for m in preview.migrations if m.script == "V1__create.sql")
            if mode == "execution":
                assert pending.analysis["status"] == "disabled"
            else:
                assert pending.analysis.get("status") != "disabled"
        applied = client.migrate()
        assert applied.success, applied.error_message
        assert client.validate().success
        assert [
            tuple(row.values()) for row in client.provider.execute_query("SELECT id FROM t")
        ] == [(7,)]
        journal = applied.journal
        assert journal.capture_objects == (mode == "full")
        summary = journal.get_migration_performance_summary("V1__create.sql")
        assert bool(summary["object_operations"]) == (mode == "full")
        if mode == "execution":
            assert summary["object_analysis"] == "disabled"
        entries = journal.get_migration_journal("V1__create.sql")
        assert any(entry.entry_type == EntryType.STATEMENT_COMPLETE for entry in entries)
        assert [
            tuple(row.values()) for row in client.provider.execute_query("SELECT event FROM audit")
        ] == [
            ("before",),
            ("before",),
            ("before",),
        ]
        assert client.undo(target_version="0.0.0").success


def test_inprocess_execution_selection_skips_ambiguous_unselected_sql(tmp_path):
    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog

    migrations = tmp_path / "sql"
    migrations.mkdir()
    (migrations / "V1__create.sql").write_text("CREATE TABLE t (id INTEGER);")
    (migrations / "V99__later.sql").write_text("WITH x AS (SELECT 1)")
    (migrations / "U1__create.sql").write_text("DROP TABLE t;")
    (migrations / "U99__later.sql").write_text("WITH x AS (SELECT 1)")
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"}}
    )
    with DBLiftClient.from_config(
        config, migrations_dir=migrations, logger=NullLog(), analysis_mode="execution"
    ) as client:
        assert client.migrate(versions="1").success
        assert client.migrate(versions="1").success  # Already applied SQL is not scanned.
        assert client.undo(target_version="0.0.0").success


def test_inprocess_async_factories_forward_selected_mode(tmp_path):
    import asyncio

    from sqlalchemy import create_engine

    from dblift.api.async_client import AsyncDBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog

    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite"), "schema": "main"}}
    )
    config_file = tmp_path / "dblift.yml"
    config_file.write_text(
        f"database:\n  type: sqlite\n  path: {tmp_path / 'db.sqlite'}\n  schema: main\n"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'engine.db'}")

    async def run():
        clients = (
            AsyncDBLiftClient.from_config(
                config, migrations_dir=tmp_path, logger=NullLog(), analysis_mode="execution"
            ),
            AsyncDBLiftClient.from_config_file(
                str(config_file),
                migrations_dir=tmp_path,
                logger=NullLog(),
                analysis_mode="execution",
            ),
            AsyncDBLiftClient.from_sqlalchemy(
                engine, migrations_dir=tmp_path, logger=NullLog(), analysis_mode="execution"
            ),
        )
        for client in clients:
            async with client:
                assert client.analysis_mode == "execution"

    try:
        asyncio.run(run())
    finally:
        engine.dispose()


@pytest.mark.parametrize("factory", ["from_config", "from_sqlalchemy"])
def test_default_full_preserves_strict_legacy_subclass_constructor(factory, tmp_path):
    from sqlalchemy import create_engine

    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog

    class LegacyClient(DBLiftClient):
        def __init__(self, provider, migrations_dir, config=None, logger=None):
            super().__init__(provider, migrations_dir, config, logger)

    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "legacy.db"), "schema": "main"}}
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:

        def create(**kwargs):
            if factory == "from_config":
                return LegacyClient.from_config(
                    config, migrations_dir=tmp_path, logger=NullLog(), **kwargs
                )
            return LegacyClient.from_sqlalchemy(
                engine, migrations_dir=tmp_path, logger=NullLog(), **kwargs
            )

        with create() as client:
            assert client.analysis_mode == "full"
        with pytest.raises(TypeError, match="analysis_mode"):
            create(analysis_mode="execution")
    finally:
        engine.dispose()


def test_sqlite_versioned_validate_and_undo_without_analysis_packages(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

root = Path('.')
migrations = root / 'sql'
migrations.mkdir()
(migrations / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(migrations / 'U1__create.sql').write_text('DROP TABLE t;')
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': str(root / 'db.sqlite'), 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=migrations,
                              logger=NullLog(), analysis_mode='execution') as client:
    assert client.analysis_mode == 'execution'
    assert client.migrate().success
    assert client.validate().success
    assert client.undo(target_version='0.0.0').success
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_invalid_mode_rejected_before_database_write(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

db = Path('db.sqlite')
sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': str(db), 'schema': 'main'}})
try:
    DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='unknown')
except ValueError as exc:
    assert 'analysis_mode' in str(exc)
else:
    raise AssertionError('invalid mode accepted')
assert not db.exists()
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_execution_journal_keeps_statements_and_labels_disabled_objects(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.journals.migration_journal import EntryType

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER); INSERT INTO t VALUES (1);')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    result = client.migrate()
    assert result.success
    journal = result.journal
    assert journal.capture_objects is False
    entries = journal.get_migration_journal('V1__create.sql')
    assert entries[0].details['object_analysis'] == 'disabled'
    assert sum(e.entry_type == EntryType.STATEMENT_COMPLETE for e in entries) == 2
    assert not any(e.entry_type == EntryType.OBJECT_CHANGE for e in entries)
    assert journal.get_migration_performance_summary('V1__create.sql')['object_analysis'] == 'disabled'
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_info_and_dry_run_label_unavailable_script_analysis(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    for result in (client.info(), client.migrate(dry_run=True)):
        pending = next(m for m in result.migrations if m.script == 'V1__create.sql')
        assert pending.analysis == {'status': 'disabled', 'reason': 'Object analysis disabled in execution mode'}
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_ambiguous_later_statement_rejected_before_history_or_user_write(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER); WITH x AS (SELECT 1)')
db = Path('db.sqlite')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': str(db), 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    outcome = client.migrate()
    assert not outcome.success
    assert "analysis_mode='full'" in outcome.error_message
if db.exists():
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_ambiguous_callback_rejected_before_any_history_write(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'beforeMigrate__check.sql').write_text('WITH x AS (SELECT 1)')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    outcome = client.migrate()
    assert not outcome.success
    assert "analysis_mode='full'" in outcome.error_message
db = Path('db.sqlite')
if db.exists():
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_execution_mode_rolls_back_later_failed_statement(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER PRIMARY KEY);')
(sql / 'V2__insert.sql').write_text('INSERT INTO t VALUES (1); INSERT INTO t VALUES (1);')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    result = client.migrate()
    assert not result.success
with sqlite3.connect('db.sqlite') as connection:
    assert connection.execute('SELECT id FROM t').fetchall() == []
    assert connection.execute('SELECT COUNT(*) FROM dblift_migration_lock').fetchone()[0] == 0
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_migrate_preflight_respects_version_selection_and_ignores_undo(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'V99__later.sql').write_text('WITH x AS (SELECT 1)')
(sql / 'U1__create.sql').write_text('WITH x AS (SELECT 1)')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate(versions='1').success
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_already_applied_sql_is_not_preflighted_again(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
script = sql / 'V1__create.sql'
script.write_text('CREATE TABLE t (id INTEGER);')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate().success
    # Model a previously applied script that the lexical classifier cannot read;
    # keep history checksum aligned so this is a no-op, not a checksum-drift test.
    changed = 'WITH x AS (SELECT 1)'
    script.write_text(changed)
    checksum = client.executor.script_manager.calculate_checksum(changed)
    with sqlite3.connect('db.sqlite') as connection:
        connection.execute('UPDATE dblift_schema_history SET checksum = ? WHERE script = ?',
                           (str(checksum), script.name))
    assert client.migrate().success
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_undo_preflight_only_reads_selected_undo_script(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'U1__create.sql').write_text('DROP TABLE t;')
(sql / 'U99__later.sql').write_text('WITH x AS (SELECT 1)')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate().success
    assert client.undo(target_version='0.0.0').success
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_ambiguous_selected_undo_does_not_issue_mutating_provider_sql(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
undo = sql / 'U1__create.sql'
undo.write_text('DROP TABLE t;')
config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate().success
    undo.write_text('WITH x AS (SELECT 1)')
    observed = []
    client.provider.connection.set_trace_callback(observed.append)
    outcome = client.undo(target_version='0.0.0')
    assert not outcome.success
    assert "analysis_mode='full'" in outcome.error_message
    assert not [query for query in observed if query.lstrip().upper().startswith(
        ('CREATE', 'ALTER', 'DROP', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE'))], observed
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_minimal_report_formatters_state_that_object_analysis_is_disabled():
    from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
    from dblift.core.logger.formatters.jsonformatter import JsonFormatter
    from dblift.core.logger.results import MigrateResult, MigrationInfo
    from dblift.core.migration.journals.migration_journal import MigrationJournal

    journal = MigrationJournal(capture_objects=False)
    journal.start_migration("V1__create.sql", {"version": "1"})
    journal.record_statement_start("CREATE TABLE t (id INTEGER)", 0)
    journal.record_statement_complete("CREATE TABLE t (id INTEGER)", 0, 1)
    journal.end_migration("V1__create.sql", success=True)
    result = MigrateResult()
    result.add_migration(MigrationInfo(script="V1__create.sql", version="1"))
    result.journal = journal

    rendered_json = json.loads(JsonFormatter().format_result(result, "main", "db", "MIGRATE"))
    assert rendered_json["object_analysis"] == "disabled"
    rendered_html = HtmlFormatter().format_result(result, "main", "db", "MIGRATE")
    assert "Object analysis disabled" in rendered_html


def test_execution_matches_full_for_repeatable_callbacks_placeholders_and_multiple_dirs(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

root = Path('primary')
extra = Path('extra')
root.mkdir()
extra.mkdir()
(root / 'beforeMigrate__audit.sql').write_text(
    'CREATE TABLE IF NOT EXISTS audit (event TEXT, value INTEGER);'
)
(root / 'beforeEach__audit.py').write_text(
    'def migrate(context):\\n'
    '    context.execute("INSERT INTO audit VALUES (?, ?)", ["before", 1])\\n'
)
(root / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(extra / 'V2__insert.sql').write_text('INSERT INTO t VALUES (${seed});')
repeatable = extra / 'R__view.sql'
repeatable.write_text('DROP VIEW IF EXISTS report; CREATE VIEW report AS SELECT id FROM t;')
summaries = []
for mode in ('full', 'execution'):
    config = DbliftConfig.from_dict({'database': {
        'type': 'sqlite', 'path': mode + '.db', 'schema': 'main'
    }})
    with DBLiftClient.from_config(
        config, migrations_dir=root, logger=NullLog(), analysis_mode=mode
    ) as client:
        first = client.migrate(additional_dirs=[extra], placeholders={'seed': 7})
        assert first.success, first.error_message
        assert {m.script for m in first.migrations} == {
            'V1__create.sql', 'V2__insert.sql', 'R__view.sql'
        }
        assert first.journal.capture_objects == (mode == 'full')
        assert client.validate(additional_dirs=[extra]).success
        rows = client.provider.execute_query('SELECT id FROM report')
        audit = client.provider.execute_query('SELECT event, value FROM audit')
        assert [tuple(row.values()) for row in rows] == [(7,)], (mode, rows)
        assert [tuple(row.values()) for row in audit] == [('before', 1)] * 3, (mode, audit)
        repeatable.write_text('DROP VIEW IF EXISTS report; CREATE VIEW report AS SELECT id + 1 AS id FROM t;')
        rerun = client.migrate(additional_dirs=[extra], placeholders={'seed': 7})
        assert rerun.success, rerun.error_message
        assert [m.script for m in rerun.migrations] == ['R__view.sql'], [
            (m.script, m.status) for m in rerun.migrations
        ]
        changed = client.provider.execute_query('SELECT id FROM report')
        summaries.append(([tuple(row.values()) for row in rows],
                          [tuple(row.values()) for row in audit],
                          [tuple(row.values()) for row in changed]))
    repeatable.write_text('DROP VIEW IF EXISTS report; CREATE VIEW report AS SELECT id FROM t;')
assert summaries[0] == summaries[1], summaries
""",
        blocked=("rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_async_sqlalchemy_factory_execution_mode_with_blocked_analysis_packages(tmp_path):
    result = run_python(
        """
import asyncio
from pathlib import Path
from sqlalchemy import create_engine
from dblift.api.async_client import AsyncDBLiftClient
from dblift.core.logger import NullLog

async def run():
    migrations = Path('sql')
    migrations.mkdir()
    (migrations / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
    (migrations / 'U1__create.sql').write_text('DROP TABLE t;')
    engine = create_engine('sqlite:///db.sqlite')
    async with AsyncDBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, logger=NullLog(), analysis_mode='execution'
    ) as client:
        assert client.analysis_mode == 'execution'
        assert (await client.migrate()).success
        assert (await client.validate()).success
        assert (await client.undo(target_version='0.0.0')).success
    engine.dispose()

asyncio.run(run())
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_execution_mode_expands_grouped_undo(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create[dblift-group-bundle].sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'V2__insert[dblift-group-bundle].sql').write_text('INSERT INTO t VALUES (1);')
(sql / 'U1__create[dblift-group-bundle].sql').write_text('DROP TABLE t;')
(sql / 'U2__insert[dblift-group-bundle].sql').write_text('DELETE FROM t WHERE id=1;')
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate().success
    undone = client.undo()
    assert undone.success, undone.error_message
    assert {m.script for m in undone.migrations} == {
        'U1__create[dblift-group-bundle].sql', 'U2__insert[dblift-group-bundle].sql'
    }
with sqlite3.connect('db.sqlite') as connection:
    assert connection.execute("SELECT name FROM sqlite_master WHERE name='t'").fetchall() == []
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_execution_mode_preserves_checksum_drift_validation(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
script = sql / 'V1__create.sql'
script.write_text('CREATE TABLE t (id INTEGER);')
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    assert client.migrate().success
    script.write_text('CREATE TABLE t (id INTEGER);\\n-- drift\\n')
    result = client.validate()
    assert not result.success
    assert 'modified since it was applied' in result.error_message
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_execution_mode_runs_cte_insert_without_sqlglot(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'V2__insert.sql').write_text(
    '\\ufeffWITH x AS (SELECT 7 AS id) INSERT INTO t SELECT id FROM x;'
)
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    outcome = client.migrate()
    assert outcome.success, outcome.error_message
    assert client.provider.execute_query('SELECT id FROM t') == [{'id': 7}]
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_nested_leading_comment_refusal_precedes_history_and_user_writes(tmp_path):
    result = run_python(
        """
import sqlite3
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
(sql / 'V1__create.sql').write_text('CREATE TABLE t (id INTEGER);')
(sql / 'V2__ambiguous.sql').write_text(
    '/* outer /* inner */ trailing */ WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x;'
)
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    outcome = client.migrate()
    assert not outcome.success
    assert "analysis_mode='full'" in outcome.error_message
with sqlite3.connect('db.sqlite') as connection:
    assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_deprecated_text_undo_request_does_not_claim_success_without_sqlglot(tmp_path):
    result = run_python(
        """
import warnings
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog

sql = Path('sql')
sql.mkdir()
script = sql / 'V1__create.sql'
script.write_text('CREATE TABLE t (id INTEGER);')
config = DbliftConfig.from_dict({'database': {
    'type': 'sqlite', 'path': 'db.sqlite', 'schema': 'main'
}})
with DBLiftClient.from_config(config, migrations_dir=sql, logger=NullLog(), analysis_mode='execution') as client:
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter('always', DeprecationWarning)
        try:
            generated = client.generate_undo_script(script)
        except ModuleNotFoundError as exc:
            assert exc.name == 'sqlglot'
        else:
            assert not generated.success
            assert 'sqlglot' in (generated.error_message or '').lower()
    assert any(issubclass(item.category, DeprecationWarning) for item in recorded)
assert not (sql / 'U1__create.sql').exists()
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
