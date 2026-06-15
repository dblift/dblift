"""Extended unit tests for :class:`db.plugins.sqlserver.provider.SqlServerProvider`."""

from unittest.mock import MagicMock

from db.plugins.sqlserver.provider import SqlServerProvider


def _provider(execute_query_map=None, raise_on_statement=None):
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    provider.statements = []
    qmap = execute_query_map or {}
    raise_set = raise_on_statement or set()

    def execute_query(sql, params=None):
        for key, rows in qmap.items():
            if key in sql:
                return rows
        return []

    def execute_statement(sql, schema=None, params=None):
        provider.statements.append((sql, schema, params))
        if any(token in sql for token in raise_set):
            raise Exception("boom")
        return 1

    provider.execute_query = execute_query
    provider.execute_statement = execute_statement
    return provider


def test_create_schema_if_not_exists_skips_when_present():
    provider = _provider({"sys.schemas": [{"cnt": 1}]})

    provider.create_schema_if_not_exists("dbo")

    assert provider.statements == []


def test_create_schema_if_not_exists_creates_when_missing():
    provider = _provider({"sys.schemas": [{"cnt": 0}]})

    provider.create_schema_if_not_exists("dbo")

    assert "CREATE SCHEMA [dbo]" in provider.statements[0][0]


def test_table_exists_true_and_false():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})
    assert provider.table_exists("dbo", "orders") is True

    provider2 = _provider({"sys.tables t": [{"cnt": 0}]})
    assert provider2.table_exists("dbo", "orders") is False


def test_get_schema_qualified_name():
    provider = _provider()
    assert provider.get_schema_qualified_name("dbo", "orders") == "[dbo].[orders]"


def test_set_current_schema_is_noop_and_logs_debug():
    provider = _provider()

    provider.set_current_schema("dbo")

    provider.log.debug.assert_called_once()


def test_get_database_version_with_rows():
    provider = _provider({"@@VERSION": [{"v": "Microsoft SQL Server 2019\nExtra line"}]})

    assert provider.get_database_version() == "Microsoft SQL Server 2019"


def test_get_database_version_without_rows():
    provider = _provider({"@@VERSION": []})

    assert provider.get_database_version() == "Unknown SQL Server Version"


def test_create_migration_history_table_creates_when_missing():
    provider = _provider({"sys.tables t": [{"cnt": 0}]})

    provider.create_migration_history_table_if_not_exists("dbo")

    assert any("CREATE TABLE" in s[0] for s in provider.statements)


def test_create_migration_history_table_skips_when_present():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    provider.create_migration_history_table_if_not_exists("dbo")

    assert provider.statements == []


def test_create_migration_history_table_with_create_schema_runs_baseline_check():
    provider = _provider(
        {
            "sys.schemas": [{"cnt": 1}],
            "sys.tables t": [{"cnt": 1}],
            "FROM [dbo].[dblift_schema_history]": [{"cnt": 0}],
        }
    )

    provider.create_migration_history_table_if_not_exists("dbo", create_schema=True)

    assert provider.statements == []


def test_check_baseline_safety_raises_when_history_present():
    provider = _provider({"FROM [dbo].[dblift_schema_history]": [{"cnt": 5}]})

    try:
        provider._check_baseline_safety("dbo", "dblift_schema_history")
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "5 migration(s)" in str(exc)


def test_check_baseline_safety_passes_with_empty_history():
    provider = _provider({"FROM [dbo].[dblift_schema_history]": [{"cnt": 0}]})

    provider._check_baseline_safety("dbo", "dblift_schema_history")  # no exception


def test_record_migration_inserts_row():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    provider.record_migration(
        "dbo",
        {
            "version": "1",
            "description": "init",
            "type": "SQL",
            "script": "V1.sql",
            "checksum": 123,
            "installed_by": "tester",
            "execution_time": 5,
            "success": True,
        },
    )

    sql, _schema, params = provider.statements[-1]
    assert "INSERT INTO" in sql
    assert params[0] == "1"
    assert params[-1] == 1


def test_record_migration_failure_uses_zero_success():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    provider.record_migration("dbo", {"version": "1", "success": False})

    _sql, _schema, params = provider.statements[-1]
    assert params[-1] == 0


def test_get_applied_migrations_no_table():
    provider = _provider({"sys.tables t": [{"cnt": 0}]})

    assert provider.get_applied_migrations("dbo") == []


def test_get_applied_migrations_returns_rows():
    rows = [{"script": "V1.sql"}]
    provider = _provider({"sys.tables t": [{"cnt": 1}], "ORDER BY installed_rank": rows})

    assert provider.get_applied_migrations("dbo") == rows


def test_record_undo_records_synthetic_undo_migration():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    assert provider.record_undo("dbo", "1", script_name="U1__undo.sql") is True

    sql, _schema, params = provider.statements[-1]
    assert "INSERT INTO" in sql
    assert params[2] == "UNDO_SQL"
    assert params[3] == "U1__undo.sql"


def test_record_undo_default_script_name():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    provider.record_undo("dbo", "2")

    _sql, _schema, params = provider.statements[-1]
    assert params[3] == "UNDO_2.sql"


def test_repair_migration_history_no_table():
    provider = _provider({"sys.tables t": [{"cnt": 0}]})

    assert provider.repair_migration_history("dbo", "V1.sql", 123) is False


def test_repair_migration_history_without_success_value():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    result = provider.repair_migration_history("dbo", "V1.sql", 999)

    assert result is True
    sql, _schema, params = provider.statements[-1]
    assert "success = 0" in sql
    assert params == [999, "V1.sql"]


def test_repair_migration_history_with_success_value():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    result = provider.repair_migration_history("dbo", "V1.sql", 999, success_value=True)

    assert result is True
    sql, _schema, params = provider.statements[-1]
    assert "success = ?" in sql
    assert params == [999, 1, "V1.sql"]


class TestCleanSchema:
    def _clean_query_map(self, temporal_type=None):
        return {
            "sys.foreign_keys fk": [{"constraint_name": "fk1", "table_name": "orders"}],
            "INFORMATION_SCHEMA.VIEWS": [{"view_name": "orders_view"}],
            "t.type = 'U'": [{"table_name": "orders", "temporal_type": temporal_type}],
            "INFORMATION_SCHEMA.ROUTINES": [
                {"routine_name": "proc1", "routine_type": "PROCEDURE"},
                {"routine_name": "func1", "routine_type": "FUNCTION"},
            ],
            "sys.sequences s": [{"sequence_name": "seq1"}],
            "sys.types t": [{"type_name": "type1"}],
            "sys.synonyms s": [{"synonym_name": "syn1"}],
        }

    def test_clean_schema_drops_all_object_types(self):
        provider = _provider(self._clean_query_map())

        summary = provider.clean_schema("dbo")

        statements = [s[0] for s in provider.statements]
        assert any("DROP CONSTRAINT [fk1]" in s for s in statements)
        assert any("DROP VIEW" in s for s in statements)
        assert any("DROP TABLE" in s for s in statements)
        assert any("DROP PROCEDURE" in s for s in statements)
        assert any("DROP FUNCTION" in s for s in statements)
        assert any("DROP SEQUENCE" in s for s in statements)
        assert any("DROP TYPE" in s for s in statements)
        assert any("DROP SYNONYM" in s for s in statements)
        assert summary.statements

    def test_clean_schema_disables_system_versioning_for_temporal_table(self):
        provider = _provider(self._clean_query_map(temporal_type=2))

        provider.clean_schema("dbo")

        statements = [s[0] for s in provider.statements]
        assert any("SET (SYSTEM_VERSIONING = OFF)" in s for s in statements)

    def test_clean_schema_logs_warning_on_drop_failures(self):
        provider = _provider(
            self._clean_query_map(temporal_type=2),
            raise_on_statement={
                "DROP CONSTRAINT",
                "DROP VIEW",
                "SET (SYSTEM_VERSIONING = OFF)",
                "DROP TABLE",
                "DROP PROCEDURE",
                "DROP FUNCTION",
                "DROP SEQUENCE",
                "DROP TYPE",
                "DROP SYNONYM",
            },
        )

        provider.clean_schema("dbo")

        assert provider.log.warning.call_count >= 6

    def test_clean_schema_handles_query_failures_for_optional_sections(self):
        class _Provider(SqlServerProvider):
            def __init__(self):
                self.log = MagicMock()
                self.calls = 0

            def execute_query(self, sql, params=None):
                self.calls += 1
                if "sys.sequences s" in sql or "sys.types t" in sql or "sys.synonyms s" in sql:
                    raise Exception("query failed")
                return []

            def execute_statement(self, sql, schema=None, params=None):
                return 1

        provider = _Provider()

        summary = provider.clean_schema("dbo")

        assert provider.log.debug.call_count >= 3
        assert summary is not None


class TestGetCleanPreview:
    def _clean_query_map(self, temporal_type=None):
        return {
            "sys.foreign_keys fk": [{"constraint_name": "fk1", "table_name": "orders"}],
            "INFORMATION_SCHEMA.VIEWS": [{"view_name": "orders_view"}],
            "t.type = 'U'": [{"table_name": "orders", "temporal_type": temporal_type}],
            "INFORMATION_SCHEMA.ROUTINES": [
                {"routine_name": "proc1", "routine_type": "PROCEDURE"},
                {"routine_name": "func1", "routine_type": "FUNCTION"},
            ],
            "sys.sequences s": [{"sequence_name": "seq1"}],
            "sys.types t": [{"type_name": "type1"}],
            "sys.synonyms s": [{"synonym_name": "syn1"}],
        }

    def test_get_clean_preview_lists_all_object_types(self):
        provider = _provider(self._clean_query_map(temporal_type=2))

        summary = provider.get_clean_preview("dbo")

        statements = summary.statements
        assert any("DROP CONSTRAINT [fk1]" in s for s in statements)
        assert any("DROP VIEW" in s for s in statements)
        assert any("SET (SYSTEM_VERSIONING = OFF)" in s for s in statements)
        assert any("DROP TABLE" in s for s in statements)
        assert any("DROP PROCEDURE" in s for s in statements)
        assert any("DROP FUNCTION" in s for s in statements)
        assert any("DROP SEQUENCE" in s for s in statements)
        assert any("DROP TYPE" in s for s in statements)
        assert any("DROP SYNONYM" in s for s in statements)
        assert provider.statements == []

    def test_get_clean_preview_handles_query_failures_for_optional_sections(self):
        class _Provider(SqlServerProvider):
            def __init__(self):
                self.log = MagicMock()

            def execute_query(self, sql, params=None):
                if "sys.sequences s" in sql or "sys.types t" in sql or "sys.synonyms s" in sql:
                    raise Exception("query failed")
                return []

            def execute_statement(self, sql, schema=None, params=None):
                return 1

        provider = _Provider()

        summary = provider.get_clean_preview("dbo")

        assert provider.log.debug.call_count >= 3
        assert summary is not None
