"""Retained core adapters and audited internal cleanup for 5.1."""

import ast
import inspect
import json
import textwrap

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger import LogFormat, NullLog
from dblift.core.logger.results import OperationResult
from dblift.core.migration.commands.base_command import BaseCommand, BaseCommandContext
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.state.migration_state_service import MigrationStateService

pytestmark = [pytest.mark.unit]


@pytest.fixture
def client(tmp_path):
    (tmp_path / "V1__first.sql").write_text("CREATE TABLE first (id INTEGER);\n")
    engine = create_engine("sqlite:///:memory:")
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path, logger=NullLog()) as value:
        yield value
    engine.dispose()


@pytest.mark.parametrize("route", ["context", "positional", "config_keyword"])
def test_retained_migrate_constructors_execute_real_scripts(client, tmp_path, route):
    context = client.executor._make_command_context()
    assert isinstance(context, BaseCommandContext)
    dependencies = dict(vars(context))
    if route == "context":
        command = MigrateCommand(context)
    elif route == "positional":
        command = MigrateCommand(*dependencies.values())
    else:
        command = MigrateCommand(**dependencies)

    result = command.execute(scripts_dir=tmp_path)

    assert result.success, result.error_message
    assert [(row.script, row.status) for row in result.migrations] == [("V1__first.sql", "SUCCESS")]
    assert client.provider.connection.execute("SELECT count(*) FROM first").fetchone()[0] == 0


@pytest.mark.parametrize("command_type", [BaseCommand, MigrateCommand])
def test_command_constructor_signatures_remain_optional_and_positional(command_type):
    parameters = list(inspect.signature(command_type).parameters.values())
    assert [parameter.name for parameter in parameters] == [
        "ctx_or_config",
        "log",
        "provider",
        "script_manager",
        "history_manager",
        "validator",
        "execution_engine",
        "migration_helpers",
        "state_manager",
        "migration_ui",
        "migration_rules",
        "journal",
        "placeholder_service",
        "config",
    ]
    assert all(parameter.default is None for parameter in parameters)
    assert all(
        parameter.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD for parameter in parameters
    )


def test_migration_checksum_stays_required_and_keyword_only():
    parameter = inspect.signature(Migration).parameters["checksum"]
    assert parameter.kind == inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError, match="checksum"):
        Migration(script_name="V1__first.sql", content="SELECT 1;")
    assert (
        Migration(script_name="V1__first.sql", content="SELECT 1;", checksum=None).checksum is None
    )


def test_public_compatibility_imports_keep_class_identity():
    from dblift.core.logger.log import LogFormat as CanonicalLogFormat
    from dblift.core.migration.commands.base_command import LogFormat as CommandLogFormat
    from dblift.core.migration.migration_types import MigrationType as CanonicalMigrationType
    from dblift.core.migration.sql.execution_contracts import ExecutionSqlParser
    from dblift.core.migration.sql.migration_sql_parser import ExecutionSqlParser as ParserContract
    from dblift.core.migration.state import MigrationStateManager as ExportedStateManager

    assert CommandLogFormat is LogFormat is CanonicalLogFormat
    assert MigrationType is CanonicalMigrationType
    assert ExportedStateManager is MigrationStateManager
    assert ExecutionSqlParser is ParserContract


def test_default_completion_hook_completes_the_result(client):
    command = BaseCommand(client.executor._make_command_context())
    result = OperationResult()
    assert result.end_time is None

    command._log_command_completion("migrate", result)

    assert result.end_time is not None
    assert result.success is True


def test_lifecycle_dispatches_subclass_header_and_completion_hooks(client):
    events = []

    class HostCommand(BaseCommand):
        def _log_command_header_update(self, command_name, **kwargs):
            events.append(("header", command_name, kwargs))

        def _log_command_completion(self, command_name, result):
            events.append(("completion", command_name, result.success))
            super()._log_command_completion(command_name, result)

    command = HostCommand(client.executor._make_command_context())
    result = OperationResult()
    returned = command._run_command_lifecycle(
        "migrate", result, lambda: events.append(("body",)), header_kwargs={"target_version": "2"}
    )

    assert returned is result
    assert result.end_time is not None
    assert events == [
        ("header", "migrate", {"target_version": "2"}),
        ("body",),
        ("completion", "migrate", True),
    ]


def test_build_state_preserves_target_selection_and_mutable_json_views(client, tmp_path):
    assert client.migrate().success
    (tmp_path / "V2__second.sql").write_text("CREATE TABLE second (id INTEGER);\n")
    (tmp_path / "V3__third.sql").write_text("CREATE TABLE third (id INTEGER);\n")
    state = client.executor.state_manager.build_state(scripts_dir=tmp_path, target_version="2")

    assert state.current_version == "1"
    assert [(row.version, row.status) for row in state.pending] == [
        ("2", "Pending"),
        ("3", "Above target"),
    ]
    assert [migration.version for migration in state.executable_pending_objects()] == ["2"]
    assert [migration.version for migration in state.pending_objects] == ["2", "3"]
    state.pending.append(state.pending[0])
    state.pending_objects.append(state.pending_objects[0])
    payload = json.loads(json.dumps(state.to_dict()))
    assert [row["version"] for row in payload["pending"]] == ["2", "3", "2"]
    assert payload["current_version"] == "1"
    assert payload["has_pending"] is True
    assert [migration.version for migration in state.executable_pending_objects()] == ["2"]


@pytest.mark.parametrize(
    ("method", "context", "expected"),
    [
        ("determine_state", {"current_version": "1", "target_version": "0"}, "Future"),
        ("determine_state", {"current_version": "3", "baseline_version": "2"}, "Missing"),
        ("determine_pending_eligibility", {"baseline_version": "2"}, "BELOW_BASELINE"),
        ("determine_pending_eligibility", {"target_version": "1"}, "ABOVE_TARGET"),
        ("determine_pending_eligibility", {"current_version": "3"}, "PENDING"),
    ],
)
def test_state_answers_keep_live_context_semantics(method, context, expected):
    migration = Migration(
        script_name="V2__second.sql", content="SELECT 1;", version="2", checksum=1
    )
    migration.success = True
    migration.resolved = False
    answer = getattr(MigrationStateService(NullLog()), method)(migration, context)
    assert answer.value == expected


@pytest.mark.parametrize(
    ("method", "key", "operation"),
    [
        (MigrationStateService.determine_state, "baseline_version", "unused_read"),
        (MigrationStateService.determine_state, "target_version", "unused_read"),
        (MigrationStateService.determine_pending_eligibility, "current_version", "unused_read"),
        (MigrationStateManager.build_state, "target_version", "duplicate_write"),
        (MigrationStateManager.build_state, "scripts_dir", "duplicate_write"),
    ],
)
def test_audited_dead_context_operations_are_absent(method, key, operation):
    # Structural cleanup guard, paired with the state behavior tests above.
    # These operations currently have no observable effect; no runtime defect is claimed.
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    if operation == "unused_read":
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "context"
            and node.value.func.attr == "get"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
            and node.value.args[0].value == key
        ]
    else:
        matches = [
            target
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "analysis_context"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == key
        ]
    assert not matches, f"audited dead {operation} remains: {method.__qualname__} {key}"
