"""ADR-0015 regression: history-table identifier normalization (BUG-03).

Three call sites used to pass the raw, unnormalized ``history_manager.history_table``
— usually ``"dblift_schema_history"`` in lowercase — to consumers that
wrap it in ANSI double-quotes. On Oracle the stored table name is
``DBLIFT_SCHEMA_HISTORY`` (Oracle folds unquoted identifiers to
UPPERCASE at DDL time), so the resulting quoted ``"dblift_schema_history"``
references a literally-lowercase table that does not exist → ORA-00942.

These tests pin the new contract: every qualification / existence-check
of the history table routes through ``MigrationHistoryManager.normalized_history_table``
so Oracle / DB2 get UPPERCASE and the lowercase-dialects get lowercase.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager


class _FakeProvider:
    """Provider stand-in: ``get_normalized_object_name`` reproduces the real dialect rule."""

    def __init__(self, dialect: str):
        self.dialect = dialect.lower()
        self.config = SimpleNamespace(database=SimpleNamespace(type=self.dialect))
        self.table_exists_calls = []
        self.repair_calls: list = []
        self.returns_exists = True

    def get_normalized_object_name(self, name: str) -> str:
        if self.dialect in ("oracle", "db2"):
            return name.upper()
        return name.lower()

    def table_exists(self, schema: str, table_name: str) -> bool:
        self.table_exists_calls.append((schema, table_name))
        return self.returns_exists

    def repair_migration_history(self, schema, script_name, checksum, **kwargs):
        self.repair_calls.append((schema, script_name, checksum, kwargs.get("table_name")))
        return True


def _make_history_manager(dialect: str, table_name: str) -> MigrationHistoryManager:
    """Bypass MigrationHistoryManager.__init__ — we only need history_table + provider."""
    mgr = MigrationHistoryManager.__new__(MigrationHistoryManager)
    mgr.provider = _FakeProvider(dialect)
    mgr.schema = "DBLIFT_TEST"
    mgr.history_table = table_name
    mgr.logger = MagicMock()
    return mgr


@pytest.mark.unit
class TestNormalizedHistoryTableProperty:
    def test_oracle_folds_to_upper(self):
        mgr = _make_history_manager("oracle", "dblift_schema_history")
        assert mgr.normalized_history_table == "DBLIFT_SCHEMA_HISTORY"

    def test_db2_folds_to_upper(self):
        mgr = _make_history_manager("db2", "dblift_schema_history")
        assert mgr.normalized_history_table == "DBLIFT_SCHEMA_HISTORY"

    @pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlserver", "sqlite"])
    def test_lowercase_dialects_stay_lower(self, dialect: str):
        mgr = _make_history_manager(dialect, "dblift_schema_history")
        assert mgr.normalized_history_table == "dblift_schema_history"

    def test_custom_mixed_case_table_preserved_case_per_dialect(self):
        """A custom name with mixed case still gets dialect-appropriate folding."""
        ora = _make_history_manager("oracle", "My_History")
        assert ora.normalized_history_table == "MY_HISTORY"
        pg = _make_history_manager("postgresql", "My_History")
        assert pg.normalized_history_table == "my_history"


@pytest.mark.unit
class TestHasHistoryTableUsesNormalizedName:
    def test_oracle_table_exists_called_with_upper(self):
        mgr = _make_history_manager("oracle", "dblift_schema_history")
        assert mgr.has_history_table is True
        # Exactly one table_exists probe, with the upper-cased name.
        assert mgr.provider.table_exists_calls == [("DBLIFT_TEST", "DBLIFT_SCHEMA_HISTORY")]

    def test_postgres_table_exists_called_with_lower(self):
        mgr = _make_history_manager("postgresql", "dblift_schema_history")
        mgr.provider.returns_exists = False
        assert mgr.has_history_table is False
        assert mgr.provider.table_exists_calls == [("DBLIFT_TEST", "dblift_schema_history")]


@pytest.mark.unit
class TestCreateSchemaAndHistoryTableGate:
    """BUG-04: create_schema_if_not_exists must only be called when create_schema=True."""

    def _make_manager(self):
        mgr = MagicMock(spec=MigrationHistoryManager)
        mgr.schema = "public"
        mgr.history_table = "dblift_schema_history"
        mgr.logger = MagicMock()
        mgr.provider = MagicMock()
        mgr.provider.create_schema_if_not_exists = MagicMock()
        mgr.provider.create_history_table_if_not_exists = MagicMock()
        # Call the real method
        mgr.create_schema_and_history_table = (
            lambda create_schema=False: MigrationHistoryManager.create_schema_and_history_table(
                mgr, create_schema=create_schema
            )
        )
        return mgr

    def test_create_schema_false_does_not_call_create_schema_if_not_exists(self):
        mgr = self._make_manager()
        mgr.create_schema_and_history_table(create_schema=False)
        mgr.provider.create_schema_if_not_exists.assert_not_called()
        mgr.provider.create_history_table_if_not_exists.assert_called_once()

    def test_create_schema_true_calls_create_schema_if_not_exists(self):
        mgr = self._make_manager()
        mgr.create_schema_and_history_table(create_schema=True)
        mgr.provider.create_schema_if_not_exists.assert_called_once_with("public")
        mgr.provider.create_history_table_if_not_exists.assert_called_once()


@pytest.mark.unit
class TestRepairChecksumUsesNormalizedName:
    """ADR-0015, fourth call site: ``repair_checksum`` passed the raw name.

    Providers qualify the table via ``get_schema_qualified_name`` and probe it
    with ``table_exists``, so the same normalization the other call sites apply
    is required here. Without it, a custom history table on Oracle/DB2 is
    referenced as a literally-lowercase identifier that does not exist —
    ``validate`` reports drift and ``repair`` silently updates nothing.
    """

    @pytest.mark.parametrize(
        ("dialect", "expected"),
        [("oracle", "MY_HISTORY"), ("db2", "MY_HISTORY"), ("postgresql", "my_history")],
    )
    def test_repair_receives_the_normalized_table_name(self, dialect: str, expected: str):
        mgr = _make_history_manager(dialect, "My_History")
        assert mgr.repair_checksum("V1__a.sql", 123) is True
        assert mgr.provider.repair_calls == [("DBLIFT_TEST", "V1__a.sql", 123, expected)]

    def test_default_table_still_normalized_per_dialect(self):
        mgr = _make_history_manager("oracle", "dblift_schema_history")
        mgr.repair_checksum("V1__a.sql", 7)
        assert mgr.provider.repair_calls[0][3] == "DBLIFT_SCHEMA_HISTORY"
