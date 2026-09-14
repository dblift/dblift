"""Generic workflows accept a provider with no explicit transaction methods."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult, RepairResult
from dblift.core.migration.commands.baseline_command import BaselineCommand
from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.transaction_policy import TransactionPolicy
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.sql.execution_statement import ExecutionStatement
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.base_provider import BaseProvider
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.base_snapshot_manager import BaseSnapshotManager
from dblift.db.provider_interfaces import DroppableObject, TransactionalProvider


class NonTransactionalProvider:
    """Record forbidden transaction lookups, even when callers swallow errors."""

    def __init__(self):
        self.transaction_lookups = []
        self.statements = []
        self.records = []
        self.dropped = []
        self.log = NullLog()
        self.quirks = BaseQuirks()
        self.config = SimpleNamespace(database=SimpleNamespace(type="sqlite", schema="main"))

    def __getattr__(self, name):
        if name in {"begin_transaction", "commit_transaction", "rollback_transaction"}:
            self.transaction_lookups.append(name)
        raise AttributeError(name)

    def is_connected(self):
        return True

    def set_current_schema(self, schema):
        pass

    def create_schema_if_not_exists(self, schema):
        pass

    def table_exists(self, schema, table):
        return False

    def get_normalized_object_name(self, name):
        return name

    def get_schema_qualified_name(self, schema, name):
        return f"{schema}.{name}"

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append(sql)
        return 1

    def record_migration(self, schema, info, table):
        self.records.append(info)

    def list_droppable_objects(self, schema):
        return [DroppableObject("items", "collection", "drop items")]

    def drop_object(self, obj):
        self.dropped.append(obj.name)


def command(command_class, provider):
    config = SimpleNamespace(
        database=SimpleNamespace(schema="main", type="sqlite"), clean_disabled=False
    )
    return command_class(
        config=config,
        log=NullLog(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MigrationHistoryManager(provider, "main", "tester", NullLog()),
        validator=None,
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def migration():
    return Migration(
        script_name="V1__items.sql",
        content="CREATE TABLE items(id INT);",
        version="1",
        type=MigrationType.SQL,
    )


def test_policy_does_not_infer_transactions_from_missing_interface():
    decision = TransactionPolicy().decide([ExecutionStatement("SELECT 1", "SELECT")], object())
    assert decision.transactional is False
    assert decision.autocommit_required is False


def test_policy_uses_interface_even_if_legacy_method_disagrees():
    provider = MagicMock(spec=TransactionalProvider)
    provider.supports_transactions.return_value = False
    assert TransactionPolicy().decide([], provider).transactional is True
    provider.supports_transactions.assert_not_called()


def test_baseline_records_without_transaction_methods():
    provider = NonTransactionalProvider()
    cmd = command(BaselineCommand, provider)
    cmd._run_preflight = lambda *args, **kwargs: None
    result = cmd.execute("1", "initial")
    assert result.success
    assert provider.records[0]["type"] == "BASELINE"
    assert provider.transaction_lookups == []


def test_clean_drops_objects_without_transaction_methods():
    provider = NonTransactionalProvider()
    result = command(CleanCommand, provider).execute()
    assert result.success, result.error_message
    assert provider.dropped == ["items"]
    assert provider.transaction_lookups == []


def test_mark_as_executed_persists_without_transaction_methods(tmp_path):
    provider = NonTransactionalProvider()
    cmd = command(MigrateCommand, provider)
    cmd._initialize_migration_execution = lambda *args, **kwargs: (True, True, None)
    cmd._update_final_state = lambda *args, **kwargs: None
    cmd.state_manager.get_current_version.return_value = None
    cmd.state_manager.build_state.return_value.executable_pending_objects.return_value = [
        migration()
    ]
    cmd.state_manager.apply_filters_to_migrations.side_effect = (
        lambda migrations, **kwargs: migrations
    )
    result = cmd.execute(tmp_path, mark_as_executed=True)
    assert result.success, result.error_message
    assert len(provider.records) == 1
    assert provider.transaction_lookups == []


def test_repair_records_delete_marker_without_transaction_methods():
    provider = NonTransactionalProvider()
    cmd = command(RepairCommand, provider)
    result = RepairResult()
    count, failed = cmd._execute_repair_loop(
        [{"type": "MISSING_SCRIPT", "script": "V1__items.sql", "version": "1"}], result
    )
    assert (count, failed) == (1, False)
    assert provider.records[0]["type"] == "DELETE"
    assert provider.transaction_lookups == []


def test_history_creation_race_retries_without_rollback(monkeypatch):
    provider = NonTransactionalProvider()
    attempts = []

    def create(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("already exists")

    provider.create_history_table_if_not_exists = create
    monkeypatch.setattr("time.sleep", lambda duration: None)
    MigrationHistoryManager(provider, "main", "tester", NullLog()).create_schema_and_history_table()
    assert len(attempts) == 2
    assert provider.transaction_lookups == []


def test_data_table_creation_does_not_probe_transaction_methods():
    provider = NonTransactionalProvider()
    BaseProvider._create_data_table_if_not_exists(provider, "main", "data_history")
    assert len(provider.statements) == 1
    assert provider.transaction_lookups == []


def test_snapshot_creation_does_not_probe_document_connection():
    provider = NonTransactionalProvider()
    provider.connection = MagicMock()
    BaseSnapshotManager(provider).create_snapshot_table_if_not_exists("main")
    assert len(provider.statements) == 1
    assert provider.connection.mock_calls == []


@pytest.mark.parametrize("failure", [False, True])
def test_sql_execution_persists_history_without_transaction_methods(failure):
    provider = NonTransactionalProvider()
    if failure:

        def fail(*args, **kwargs):
            raise RuntimeError("statement failed")

        provider.execute_statement = fail
    history = MigrationHistoryManager(provider, "main", "tester", NullLog())
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect="sqlite"),
        log=NullLog(),
        history_manager=history,
    )
    result = MigrateResult()
    engine.execute_migration(migration(), result)
    assert result.success is (not failure), result.error_message
    assert len(provider.records) == 1
    assert provider.records[0]["success"] is (not failure)
    assert provider.transaction_lookups == []


@pytest.mark.parametrize("failure", [False, True])
def test_python_execution_persists_history_without_transaction_methods(tmp_path, failure):
    provider = NonTransactionalProvider()
    script = tmp_path / "V1__items.py"
    content = "def migrate(context):\n    context.provider.statements.append('python ran')\n"
    if failure:
        content += "    raise RuntimeError('script failed')\n"
    script.write_text(content)
    history = MigrationHistoryManager(provider, "main", "tester", NullLog())
    engine = ExecutionEngine(
        provider, SqlAnalyzer(dialect="sqlite"), NullLog(), history_manager=history
    )
    result = MigrateResult()
    engine.execute_migration(Migration(script_path=script), result)
    assert result.success is (not failure), result.error_message
    assert provider.statements == ["python ran"]
    assert len(provider.records) == 1
    assert provider.records[0]["success"] is (not failure)
    assert provider.transaction_lookups == []


@pytest.mark.parametrize("failure", [False, True])
def test_sql_callback_never_uses_missing_transaction_methods(failure):
    provider = NonTransactionalProvider()
    callback = Migration(
        script_name="beforeMigrate__items.sql", content="CREATE TABLE items(id INT);"
    )
    engine = ExecutionEngine(provider, SqlAnalyzer(dialect="sqlite"), NullLog())
    if failure:

        def fail(*args, **kwargs):
            raise RuntimeError("callback failed")

        provider.execute_statement = fail
        with pytest.raises(RuntimeError, match="callback failed"):
            engine.execute_callback(callback)
    else:
        engine.execute_callback(callback)
        assert len(provider.statements) == 1
    assert provider.transaction_lookups == []
