from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy import create_engine

from api import DBLiftClient
from core.migration.commands.clean_command import CleanCommand
from db.provider_interfaces import DroppableObject


def test_clean_drops_objects_without_introspector(tmp_path: Path):
    m = tmp_path / "migrations"
    m.mkdir()
    (m / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    c = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(m))

    c.migrate()
    res = c.clean(clean_enabled=True)

    assert res.success
    insp = sa.inspect(engine)
    assert "t" not in insp.get_table_names()


def test_clean_drops_sqlite_tables_with_foreign_keys_without_introspector(tmp_path: Path):
    m = tmp_path / "migrations"
    m.mkdir()
    (m / "V1_0_0__parent_child.sql").write_text(
        "\n".join(
            [
                "CREATE TABLE parent (id INTEGER PRIMARY KEY);",
                "CREATE TABLE child (",
                "    id INTEGER PRIMARY KEY,",
                "    parent_id INTEGER NOT NULL REFERENCES parent(id)",
                ");",
            ]
        )
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    c = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(m))

    c.migrate()
    res = c.clean(clean_enabled=True)

    assert res.success
    insp = sa.inspect(engine)
    assert "parent" not in insp.get_table_names()
    assert "child" not in insp.get_table_names()


def test_sqlite_clean_command_emits_foreign_key_control_statements(tmp_path: Path):
    from config import DbliftConfig
    from db.plugins.sqlite.config import SQLiteConfig
    from db.plugins.sqlite.provider import SQLiteProvider

    db_path = tmp_path / "db.sqlite"
    provider = SQLiteProvider(
        DbliftConfig(database=SQLiteConfig(type="sqlite", path=str(db_path), schema="main")),
        MagicMock(),
    )
    provider.connect()
    provider.execute_statement("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    provider.execute_statement(
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
    )

    objects = provider.list_droppable_objects("main")

    assert objects[0].drop_sql == "PRAGMA foreign_keys = OFF"
    assert objects[0].record_result is False
    assert objects[-1].drop_sql == "PRAGMA foreign_keys = ON"
    assert objects[-1].record_result is False


def test_clean_command_executes_provider_droppable_objects():
    provider = MagicMock()
    provider.list_droppable_objects.return_value = [
        DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
    ]
    provider.commit_transaction.return_value = None

    cmd = CleanCommand(
        config=SimpleNamespace(
            clean_disabled=False,
            database=SimpleNamespace(schema="main", type="sqlite"),
        ),
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )

    result = cmd.execute()

    assert result.success
    provider.execute_statement.assert_called_once_with('DROP TABLE "t"')
    provider.clean_schema.assert_not_called()
    assert "t" in result.tables_dropped


def test_clean_command_executes_unrecorded_control_statements_without_result_entry():
    provider = MagicMock()
    provider.list_droppable_objects.return_value = [
        DroppableObject(
            name="foreign_key_checks_off",
            object_type="clean_control",
            drop_sql="SET FOREIGN_KEY_CHECKS = 0",
            record_result=False,
        ),
        DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"'),
    ]
    provider.commit_transaction.return_value = None

    cmd = CleanCommand(
        config=SimpleNamespace(
            clean_disabled=False,
            database=SimpleNamespace(schema="main", type="mysql"),
        ),
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )

    result = cmd.execute()

    assert result.success
    provider.execute_statement.assert_any_call("SET FOREIGN_KEY_CHECKS = 0")
    provider.execute_statement.assert_any_call('DROP TABLE "t"')
    assert "clean_control" not in result.get_objects_by_type()
    assert "t" in result.tables_dropped


def test_clean_command_dry_run_hides_unrecorded_control_statements():
    provider = MagicMock()
    provider.list_droppable_objects.return_value = [
        DroppableObject(
            name="foreign_key_checks_off",
            object_type="clean_control",
            drop_sql="SET FOREIGN_KEY_CHECKS = 0",
            record_result=False,
        ),
        DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"'),
    ]
    log = MagicMock()

    cmd = CleanCommand(
        config=SimpleNamespace(
            clean_disabled=False,
            database=SimpleNamespace(schema="main", type="mysql"),
        ),
        log=log,
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )

    result = cmd.execute(dry_run=True)

    assert result.success
    provider.execute_statement.assert_not_called()
    log.info.assert_any_call("  Would drop table: t")
    assert all("clean_control" not in call.args[0] for call in log.info.call_args_list if call.args)
