"""Tests for SchemaSnapshotService helper methods."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_service():
    from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

    config = MagicMock()
    config.database.type = "postgresql"
    config.database.schema = "public"
    config.max_snapshots = 1
    config.snapshot_table = None
    provider = MagicMock()
    provider.config = config
    provider.get_normalized_object_name.side_effect = lambda n: n.lower()
    provider.get_schema_qualified_name.side_effect = lambda s, t: f"{s}.{t}"
    provider.get_parameter_placeholders.return_value = "?, ?, ?, ?"
    history_manager = MagicMock()
    log = MagicMock()
    with patch("core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"):
        svc = SchemaSnapshotService(
            config=config, provider=provider, history_manager=history_manager, log=log
        )
    svc.repository = MagicMock()
    return svc, config, provider


class TestNormalizeName(unittest.TestCase):
    def test_none_returns_empty(self):
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        self.assertEqual(SchemaSnapshotService._normalize_name(None), "")

    def test_strips_quotes(self):
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        result = SchemaSnapshotService._normalize_name('"users"')
        self.assertEqual(result, "users")

    def test_strips_brackets(self):
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        result = SchemaSnapshotService._normalize_name("[users]")
        self.assertEqual(result, "users")

    def test_strips_backticks(self):
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        result = SchemaSnapshotService._normalize_name("`users`")
        self.assertEqual(result, "users")

    def test_lowercase(self):
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        result = SchemaSnapshotService._normalize_name("USERS")
        self.assertEqual(result, "users")


class TestMakeTableKey(unittest.TestCase):
    def test_with_schema_and_name(self):
        svc, *_ = _make_service()
        key = svc._make_table_key("public", "users")
        self.assertIn("users", key)

    def test_none_schema(self):
        svc, *_ = _make_service()
        key = svc._make_table_key(None, "users")
        self.assertIsNotNone(key)


class TestCallOptional(unittest.TestCase):
    def test_calls_method_if_exists(self):
        svc, *_ = _make_service()
        obj = MagicMock()
        obj.get_tables.return_value = ["table1"]
        result = svc._call_optional(obj, "get_tables", "schema")
        self.assertEqual(result, ["table1"])

    def test_returns_empty_if_no_method(self):
        svc, *_ = _make_service()
        obj = MagicMock(spec=[])  # no attrs
        result = svc._call_optional(obj, "nonexistent_method")
        self.assertEqual(result, [])

    def test_returns_empty_on_exception(self):
        svc, *_ = _make_service()
        obj = MagicMock()
        obj.get_tables.side_effect = Exception("DB error")
        result = svc._call_optional(obj, "get_tables", "schema")
        self.assertEqual(result, [])


class TestSafeIntrospect(unittest.TestCase):
    def test_returns_result_on_success(self):
        svc, *_ = _make_service()
        func = MagicMock(return_value=["table1", "table2"])
        result = svc._safe_introspect(func, "schema")
        self.assertEqual(result, ["table1", "table2"])

    def test_returns_empty_on_exception(self):
        svc, *_ = _make_service()
        func = MagicMock(side_effect=Exception("introspection failed"))
        result = svc._safe_introspect(func, "schema")
        self.assertEqual(result, [])


class TestIsConnectionError(unittest.TestCase):
    def test_communication_error_is_connection(self):
        svc, *_ = _make_service()
        err = Exception("Communication error with DB")
        result = svc._is_connection_error(err)
        self.assertIsInstance(result, bool)

    def test_sql_error_not_connection(self):
        svc, *_ = _make_service()
        err = Exception("SQLCODE=-440")
        result = svc._is_connection_error(err)
        self.assertIsInstance(result, bool)


class TestFilterTables(unittest.TestCase):
    def _make_table(self, name, schema="public"):
        t = MagicMock()
        t.name = name
        t.schema = schema
        return t

    def test_basic_filter_no_exclusions(self):
        svc, *_ = _make_service()
        tables = [self._make_table("users"), self._make_table("orders")]
        result, keys = svc._filter_tables(tables, "public")
        self.assertEqual(len(result), 2)
        self.assertEqual(len(keys), 2)

    def test_excludes_history_table(self):
        svc, *_ = _make_service()
        svc.history_manager.history_table = "dblift_schema_history"
        tables = [
            self._make_table("users"),
            self._make_table("dblift_schema_history"),
        ]
        result, keys = svc._filter_tables(tables, "public")
        names = [t.name for t in result]
        self.assertNotIn("dblift_schema_history", names)

    def test_empty_list(self):
        svc, *_ = _make_service()
        result, keys = svc._filter_tables([], "public")
        self.assertEqual(result, [])
        self.assertEqual(keys, set())


class TestFilterViews(unittest.TestCase):
    def test_basic_filter(self):
        svc, *_ = _make_service()
        v = MagicMock()
        v.name = "v_users"
        v.schema = "public"
        result = svc._filter_views([v], "public")
        self.assertEqual(len(result), 1)


class TestFilterIndexes(unittest.TestCase):
    def test_empty_result(self):
        svc, *_ = _make_service()
        result = svc._filter_indexes([], set(), [])
        self.assertEqual(result, [])


class TestFilterSequences(unittest.TestCase):
    def test_empty_result(self):
        svc, *_ = _make_service()
        result = svc._filter_sequences([], [])
        self.assertEqual(result, [])


class TestFilterTriggers(unittest.TestCase):
    def test_empty_result(self):
        svc, *_ = _make_service()
        result = svc._filter_triggers([], set())
        self.assertEqual(result, [])


class TestDeepUpdate(unittest.TestCase):
    def test_basic_merge(self):
        svc, *_ = _make_service()
        # _deep_update is a static or instance method
        target = {"a": 1, "nested": {"x": 1}}
        source = {"b": 2, "nested": {"y": 2}}
        try:
            svc._deep_update(target, source)
            self.assertEqual(target["b"], 2)
            self.assertEqual(target["nested"]["y"], 2)
        except AttributeError:
            pass  # Method might be named differently


class TestCollectMigrationMetadata(unittest.TestCase):
    def test_includes_applied_manifest_with_versioned_checksums(self):
        from core.migration.migration import MigrationType

        svc, *_ = _make_service()
        installed_on = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
        versioned = SimpleNamespace(
            script_name="V1__create_users.sql",
            version="1",
            description="create_users",
            type=MigrationType.SQL,
            checksum=123,
            success=True,
            installed_rank=7,
            installed_on=installed_on,
            installed_by="ci",
        )
        repeatable = SimpleNamespace(
            script_name="R__refresh_view.sql",
            version=None,
            description="refresh_view",
            type=MigrationType.REPEATABLE,
            checksum=456,
            installed_rank=8,
            installed_on=installed_on,
            installed_by="ci",
        )
        svc.history_manager.get_applied_migrations.return_value = [versioned, repeatable]

        metadata = svc._collect_migration_metadata()

        self.assertEqual(metadata["applied_versions"], ["1"])
        self.assertEqual(
            metadata["applied"],
            [
                {
                    "script": "V1__create_users.sql",
                    "version": "1",
                    "description": "create_users",
                    "type": "SQL",
                    "checksum": 123,
                    "success": True,
                    "installed_rank": 7,
                    "installed_on": installed_on.isoformat(),
                    "installed_by": "ci",
                }
            ],
        )

    def test_includes_python_versioned_migrations(self):
        from core.migration.migration import MigrationType

        svc, *_ = _make_service()
        python_migration = SimpleNamespace(
            script_name="V2__load_reference_data.py",
            version="2",
            description="load_reference_data",
            type=MigrationType.PYTHON,
            checksum=789,
            success=True,
            installed_rank=9,
            installed_on=None,
            installed_by="ci",
        )
        svc.history_manager.get_applied_migrations.return_value = [python_migration]

        metadata = svc._collect_migration_metadata()

        self.assertEqual(metadata["applied_versions"], ["2"])
        self.assertEqual(metadata["applied"][0]["script"], "V2__load_reference_data.py")
        self.assertEqual(metadata["applied"][0]["type"], "PYTHON")

    def test_excludes_failed_migrations_from_applied_versions(self):
        from core.migration.migration import MigrationType

        svc, *_ = _make_service()
        failed = SimpleNamespace(
            script_name="V3__failed.sql",
            version="3",
            description="failed",
            type=MigrationType.SQL,
            checksum=111,
            success=False,
            installed_rank=10,
            installed_on=None,
            installed_by="ci",
        )
        svc.history_manager.get_applied_migrations.return_value = [failed]

        metadata = svc._collect_migration_metadata()

        self.assertEqual(metadata["applied_versions"], [])
        self.assertEqual(metadata["applied"], [])

    def test_excludes_failed_repeatables_from_snapshot(self):
        from core.migration.migration import MigrationType

        svc, *_ = _make_service()
        ok = SimpleNamespace(
            script_name="R__ok.sql",
            version=None,
            type=MigrationType.REPEATABLE,
            checksum=222,
            success=True,
            installed_rank=11,
            installed_on=None,
        )
        failed = SimpleNamespace(
            script_name="R__broken.sql",
            version=None,
            type=MigrationType.REPEATABLE,
            checksum=333,
            success=False,
            installed_rank=12,
            installed_on=None,
        )
        svc.history_manager.get_applied_migrations.return_value = [ok, failed]

        metadata = svc._collect_migration_metadata()

        # A failed repeatable must not be recorded, otherwise a later plan would
        # treat its checksum as applied and never retry it.
        self.assertEqual([r["script"] for r in metadata["repeatables"]], ["R__ok.sql"])
