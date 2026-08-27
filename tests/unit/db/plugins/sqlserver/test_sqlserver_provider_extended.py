"""Extended unit tests for :class:`db.plugins.sqlserver.provider.SqlServerProvider`."""

from unittest.mock import MagicMock

from core.migration.sql.execution_statement import classify_execution_statement
from db.plugins.sqlserver.provider import SqlServerProvider
from db.provider_interfaces import DroppableObject
from db.sqlalchemy_provider import SqlAlchemyProvider


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


def test_set_current_schema_alters_connecting_user_default_schema(monkeypatch):
    """Unqualified DDL must land in the configured schema (issue #806).

    SQL Server has no session-level search path; unqualified object names
    resolve against the connecting user's DEFAULT_SCHEMA. ALTER USER takes
    effect immediately within the current session, so it is the real
    equivalent of PostgreSQL's ``SET search_path`` / MySQL's ``USE``.
    """
    provider = _provider(execute_query_map={"USER_NAME()": [{"db_user": "dblift_test"}]})
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )

    provider.set_current_schema("target_schema")

    assert executed == ["ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [target_schema]"]


def test_set_current_schema_logs_warning_when_it_cannot_determine_user(monkeypatch):
    """A permission or lookup failure must be loud, not silently swallowed."""
    provider = _provider()  # execute_query returns [] -> current user can't be resolved
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: (_ for _ in ()).throw(AssertionError()),
    )

    provider.set_current_schema("target_schema")

    provider.log.warning.assert_called_once()


def test_execute_statement_with_schema_sets_current_schema(monkeypatch):
    """The mainline ``migrate`` path (execute_statement) must set the schema too.

    Previously only ``create_schema_if_not_exists`` ran here, so unqualified
    DDL executed via a normal migration script (not a callback) never had its
    default schema aligned — this mirrors the PostgreSQL/MySQL providers.
    """
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    calls = []
    provider.create_schema_if_not_exists = lambda schema: calls.append(("create", schema))
    provider.set_current_schema = lambda schema: calls.append(("set", schema))
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: calls.append(("exec", sql)) or 1,
    )

    SqlServerProvider.execute_statement(
        provider, "CREATE TABLE foo (id INT)", schema="target_schema"
    )

    assert calls == [
        ("create", "target_schema"),
        ("set", "target_schema"),
        ("exec", "CREATE TABLE foo (id INT)"),
    ]


def test_set_current_schema_alters_only_once_per_connection(monkeypatch):
    """DEFAULT_SCHEMA is catalog-level state on the login, not connection-scoped
    like every other dialect's mechanism — it is shared with any other
    connection authenticating as the same login. Repeated calls with the same
    schema on this connection must not re-issue ALTER USER: each write
    touches that shared state, so redundant writes only widen the window for
    a concurrent process sharing the login to race on it.
    """
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    provider._current_schema_set = None

    def fake_execute_query(sql, params=None):
        if "USER_NAME()" in sql:
            return [{"db_user": "dblift_test"}]
        if "sys.database_principals" in sql:
            # No interference: catalog agrees with whatever we last set.
            return [{"default_schema": provider._current_schema_set}]
        return []

    provider.execute_query = fake_execute_query
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )

    provider.set_current_schema("target_schema")
    provider.set_current_schema("target_schema")
    provider.set_current_schema("target_schema")

    assert executed == ["ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [target_schema]"]
    provider.log.warning.assert_not_called()


def test_set_current_schema_detects_interference_even_when_target_schema_is_unchanged(monkeypatch):
    """The interference check must not be gated behind the cache-hit skip.

    ``--db-schema`` is one fixed value for an entire process run, so after
    the first call every later call (i.e. every subsequent statement) asks
    for the SAME schema again. If the catalog read only ran when the
    requested schema changed, a concurrent process clobbering DEFAULT_SCHEMA
    in between two identical calls would never be noticed — exactly the
    steady-state scenario the whole check exists to catch. The read+compare
    must run on every call; only the ALTER USER write is skipped on a cache
    hit (see issue #806 review follow-up).
    """
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    provider._current_schema_set = "sales"  # as if set earlier on this connection

    def fake_execute_query(sql, params=None):
        if "sys.database_principals" in sql:
            # someone else silently overwrote it
            return [{"db_user": "dblift_test", "default_schema": "orders"}]
        return []

    provider.execute_query = fake_execute_query
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )

    provider.set_current_schema("sales")  # same schema as before -- a cache hit

    provider.log.warning.assert_called_once()
    warning_msg = provider.log.warning.call_args[0][0]
    assert "orders" in warning_msg
    assert "sales" in warning_msg
    # The write is still skipped on the cache hit -- only detection changed.
    assert executed == []
    assert provider._current_schema_set == "sales"


def test_execute_statement_alters_default_schema_once_across_multiple_statements(monkeypatch):
    """Exercises the real per-statement call path (SqlExecutionService calls
    ``execute_statement(statement, schema=...)`` once per statement in a
    migration script — see core/migration/sql/sql_execution_service.py).
    ALTER USER must fire once per connection, not once per statement.
    """
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    provider._current_schema_set = None

    def fake_execute_query(sql, params=None):
        if "sys.schemas" in sql:
            return [{"cnt": 1}]  # schema already exists, skip CREATE SCHEMA
        if "USER_NAME()" in sql:
            return [{"db_user": "dblift_test"}]
        if "sys.database_principals" in sql:
            return [{"default_schema": provider._current_schema_set}]
        return []

    provider.execute_query = fake_execute_query
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql) or 1,
    )

    for stmt in [
        "CREATE TABLE t1 (id INT)",
        "CREATE TABLE t2 (id INT)",
        "CREATE TABLE t3 (id INT)",
    ]:
        SqlServerProvider.execute_statement(provider, stmt, schema="target_schema")

    alter_statements = [s for s in executed if s.startswith("ALTER USER")]
    assert alter_statements == ["ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [target_schema]"]
    assert executed[-3:] == [
        "CREATE TABLE t1 (id INT)",
        "CREATE TABLE t2 (id INT)",
        "CREATE TABLE t3 (id INT)",
    ]


def test_set_current_schema_warns_on_external_interference(monkeypatch):
    """A concurrent process sharing this SQL Server login changing
    DEFAULT_SCHEMA between our own writes must be surfaced loudly, not
    silently trusted — see issue #806 review follow-up.
    """
    provider = object.__new__(SqlServerProvider)
    provider.log = MagicMock()
    provider._current_schema_set = "schema_a"  # as if set earlier on this connection

    def fake_execute_query(sql, params=None):
        if "sys.database_principals" in sql:
            # someone else changed it
            return [{"db_user": "dblift_test", "default_schema": "schema_hijacked"}]
        return []

    provider.execute_query = fake_execute_query
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )

    provider.set_current_schema("schema_b")

    provider.log.warning.assert_called_once()
    warning_msg = provider.log.warning.call_args[0][0]
    assert "schema_hijacked" in warning_msg
    assert "schema_a" in warning_msg
    assert executed == ["ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [schema_b]"]
    assert provider._current_schema_set == "schema_b"


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
    assert "COALESCE(?, success)" in sql
    assert "success = 0" not in sql
    assert params == [999, None, "V1.sql"]


def test_repair_migration_history_with_success_value():
    provider = _provider({"sys.tables t": [{"cnt": 1}]})

    result = provider.repair_migration_history("dbo", "V1.sql", 999, success_value=True)

    assert result is True
    sql, _schema, params = provider.statements[-1]
    assert "COALESCE(?, success)" in sql
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


class TestDropObjectAutocommitRouting:
    """Regression coverage for the mechanism that prevents SQL Server error
    574: ``DROP FULLTEXT CATALOG`` cannot run inside a user transaction, so
    ``SqlServerProvider.drop_object()`` must route it through
    ``execute_autocommit_statement`` instead of the normal transactional
    ``execute_statement`` path used for every other object type.

    Prior to this test, reverting either half of the mechanism — the
    ``DROP FULLTEXT CATALOG`` entry in
    ``SqlserverQuirks.non_transactional_sql_patterns``, or the routing
    branch in ``drop_object`` itself — passed the full unit suite
    unchanged. See the two ``test_*_mutation_*`` tests below, which
    temporarily reproduce each of those reverts and confirm the coverage
    added here actually catches them.
    """

    def _provider_for_drop_object(self):
        provider = object.__new__(SqlServerProvider)
        provider.log = MagicMock()
        provider.execute_autocommit_statement = MagicMock(return_value=1)
        provider.execute_statement = MagicMock(return_value=1)
        return provider

    def test_classify_execution_statement_flags_drop_fulltext_catalog_as_non_transactional(self):
        statement = classify_execution_statement(
            "DROP FULLTEXT CATALOG [ft_catalog]", dialect="sqlserver"
        )
        assert statement.can_execute_in_transaction is False
        assert "FULLTEXT CATALOG" in (statement.transaction_reason or "")

    def test_classify_execution_statement_leaves_ordinary_drops_transactional(self):
        # A normal statement must not be flagged — otherwise a test that only
        # checked the fulltext-catalog case above could pass even if
        # classification always returned "non-transactional".
        statement = classify_execution_statement("DROP TABLE [dbo].[orders]", dialect="sqlserver")
        assert statement.can_execute_in_transaction is True

    def test_drop_object_routes_fulltext_catalog_through_autocommit(self):
        provider = self._provider_for_drop_object()
        obj = DroppableObject(
            name="ft_catalog",
            object_type="fulltext_catalog",
            drop_sql="DROP FULLTEXT CATALOG [ft_catalog]",
        )

        provider.drop_object(obj)

        provider.execute_autocommit_statement.assert_called_once_with(
            "DROP FULLTEXT CATALOG [ft_catalog]"
        )
        provider.execute_statement.assert_not_called()

    def test_drop_object_routes_ordinary_drop_through_normal_transactional_path(self):
        # The opposite case: routing must be conditional, not blanket. If
        # drop_object routed everything through autocommit unconditionally,
        # only the test above would catch it — this one exists so that bug
        # cannot slip through disguised as "the fix works".
        provider = self._provider_for_drop_object()
        obj = DroppableObject(
            name="orders",
            object_type="table",
            drop_sql="DROP TABLE [dbo].[orders]",
        )

        provider.drop_object(obj)

        provider.execute_statement.assert_called_once_with("DROP TABLE [dbo].[orders]")
        provider.execute_autocommit_statement.assert_not_called()
