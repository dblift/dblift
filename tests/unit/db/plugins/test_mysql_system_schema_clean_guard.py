"""System databases must never become MySQL or MariaDB clean targets."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
from dblift.db.plugins.mysql.provider import MySqlProvider


@pytest.mark.parametrize(
    "schema",
    [
        "mysql",
        " mysql ",
        "sys",
        "information_schema",
        "performance_schema",
        "INFORMATION_SCHEMA",
    ],
)
@pytest.mark.parametrize("method", ["clean_schema", "get_clean_preview"])
def test_operations_refuse_system_database_before_sql(schema, method):
    executor = MagicMock()
    executor.execute_query.return_value = []
    operations = MySqlSchemaOperations(executor)
    connection = MagicMock()

    with pytest.raises(ValueError, match="system database"):
        getattr(operations, method)(connection, schema)

    assert executor.mock_calls == []
    assert connection.mock_calls == []


@pytest.mark.parametrize("provider_class", [MySqlProvider, MariadbProvider])
@pytest.mark.parametrize("method", ["clean_schema", "list_droppable_objects"])
def test_provider_refuses_system_database(provider_class, method):
    provider = object.__new__(provider_class)
    provider.query_executor = MagicMock()
    provider.query_executor.execute_query.return_value = []
    provider.log = MagicMock()
    provider._ensure_connection = MagicMock(return_value=MagicMock())

    with pytest.raises(ValueError, match="system database"):
        getattr(provider, method)("mysql")

    provider.query_executor.execute_statement.assert_not_called()
    provider.query_executor.execute_query.assert_not_called()


@pytest.mark.parametrize("schema", ["mysql_app", "system", "sys_archive"])
def test_clean_keeps_user_database_names(schema):
    executor = MagicMock()
    executor.execute_query.return_value = []
    executor.get_quoted_schema_name.side_effect = lambda name: f"`{name}`"
    operations = MySqlSchemaOperations(executor)
    connection = MagicMock()

    operations.clean_schema(connection, schema)

    executor.execute_statement.assert_any_call(connection, f"USE `{schema}`")


@pytest.mark.parametrize("provider_class", [MySqlProvider, MariadbProvider])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("schema", ["mysql", "MYSQL"])
@pytest.mark.parametrize("probe_fails", [False, True])
def test_clean_command_reports_system_database_refusal(
    provider_class, dry_run, schema, probe_fails, tmp_path
):
    provider = object.__new__(provider_class)
    provider.query_executor = MagicMock()
    provider.query_executor.execute_query.return_value = []
    provider.log = MagicMock()
    provider._ensure_connection = MagicMock(return_value=MagicMock())
    provider.set_current_schema = MagicMock()
    provider.drop_object = MagicMock()
    if probe_fails:
        provider.query_executor.execute_query.side_effect = RuntimeError("case mode unavailable")
    config = MagicMock()
    config.database.schema = schema
    config.clean_disabled = False
    command = CleanCommand(
        config=config,
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
    command._run_preflight = MagicMock()
    command._log_command_header_update = MagicMock()

    command._prepare_analysis_for_sql_callbacks = MagicMock()
    callback_effect = tmp_path / "callback-ran"
    command._execute_callbacks = MagicMock(
        side_effect=lambda *args, **kwargs: callback_effect.write_text("changed database")
    )

    result = command.execute(dry_run=dry_run, scripts_dir=tmp_path)

    assert not callback_effect.exists()
    provider.set_current_schema.assert_not_called()
    command._run_preflight.assert_not_called()
    command._prepare_analysis_for_sql_callbacks.assert_not_called()
    assert result.success is False
    expected_error = (
        "case mode unavailable" if probe_fails and schema == "MYSQL" else "system database"
    )
    assert expected_error in result.error_message
    provider.drop_object.assert_not_called()
    provider.query_executor.execute_statement.assert_not_called()


@pytest.mark.parametrize("schema", ["MYSQL", "Sys", "PERFORMANCE_SCHEMA"])
@pytest.mark.parametrize("case_mode", [0, 1, 2])
@pytest.mark.parametrize("method", ["clean_schema", "get_clean_preview"])
def test_mixed_case_target_uses_server_case_rules(schema, case_mode, method):
    executor = MagicMock()
    executor.execute_query.side_effect = lambda connection, sql, *args, **kwargs: (
        [{"lower_case_table_names": case_mode}] if "@@lower_case_table_names" in sql else []
    )
    executor.get_quoted_schema_name.side_effect = lambda name: f"`{name}`"
    operations = MySqlSchemaOperations(executor)
    connection = MagicMock()

    if case_mode == 0:
        getattr(operations, method)(connection, schema)
    else:
        with pytest.raises(ValueError, match="system database"):
            getattr(operations, method)(connection, schema)
        executor.execute_statement.assert_not_called()
        assert executor.execute_query.call_count == 1


@pytest.mark.parametrize("case_rows", [[], [{"lower_case_table_names": "unknown"}]])
def test_unknown_case_mode_refuses_mixed_case_clean(case_rows):
    executor = MagicMock()
    executor.execute_query.return_value = case_rows
    operations = MySqlSchemaOperations(executor)

    with pytest.raises(ValueError, match="system database"):
        operations.clean_schema(MagicMock(), "MYSQL")

    executor.execute_statement.assert_not_called()
