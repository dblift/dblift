"""Tests for MigrationDataService."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from core.migration.state.migration_data_service import MigrationDataService
from core.migration.state.migration_state_service import MigrationStateService


def make_migration(
    version="1",
    type="SQL",
    script_name="V1__test.sql",
    success=True,
    installed_rank=1,
    description="test",
    checksum="abc",
    installed_on=None,
    installed_by="user",
    execution_time=100,
    resolved=True,
):
    m = Mock()
    m.version = version
    m.type = type
    m.script_name = script_name
    m.success = success
    m.installed_rank = installed_rank
    m.description = description
    m.checksum = checksum
    m.installed_on = installed_on
    m.installed_by = installed_by
    m.execution_time = execution_time
    m.resolved = resolved
    return m


@pytest.fixture
def logger():
    return MagicMock()


@pytest.fixture
def service(logger):
    return MigrationDataService(logger, scripts_dir=Path("/tmp/scripts"), target_version="5")


# ---------- _get_migration_type ----------


@pytest.mark.unit
class TestGetMigrationType:
    def test_string_type(self, service):
        m = make_migration(type="SQL")
        assert service._get_migration_type(m) == "SQL"

    def test_string_lowercase_uppercased(self, service):
        m = make_migration(type="sql")
        assert service._get_migration_type(m) == "SQL"

    def test_enum_type_with_name(self, service):
        enum_type = Mock()
        enum_type.name = "REPEATABLE"
        m = make_migration()
        m.type = enum_type
        assert service._get_migration_type(m) == "REPEATABLE"

    def test_empty_type(self, service):
        m = make_migration(type="")
        assert service._get_migration_type(m) == ""


# ---------- _is_migration_successful ----------


@pytest.mark.unit
class TestIsMigrationSuccessful:
    def test_true_success(self, service):
        m = make_migration(success=True)
        assert service._is_migration_successful(m) is True

    def test_false_success(self, service):
        m = make_migration(success=False)
        assert service._is_migration_successful(m) is False


# ---------- _get_undone_versions ----------


@pytest.mark.unit
class TestGetUndoneVersions:
    def test_finds_successful_undo_sql(self, service):
        migrations = [
            make_migration(version="1", type="SQL", installed_rank=1),
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=2),
        ]
        result = service._get_undone_versions(migrations)
        assert result == {"1"}

    def test_ignores_failed_undo(self, service):
        migrations = [
            make_migration(version="1", type="UNDO_SQL", success=False, installed_rank=2),
        ]
        result = service._get_undone_versions(migrations)
        assert result == set()

    def test_ignores_non_undo(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
        ]
        result = service._get_undone_versions(migrations)
        assert result == set()

    def test_empty_list(self, service):
        assert service._get_undone_versions([]) == set()


# ---------- _get_reapplied_versions ----------


@pytest.mark.unit
class TestGetReappliedVersions:
    def test_reapplied_after_undo(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=2),
            make_migration(version="1", type="SQL", success=True, installed_rank=3),
        ]
        result = service._get_reapplied_versions(migrations)
        assert result == {"1"}

    def test_not_reapplied_if_no_sql_after_undo(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=2),
        ]
        result = service._get_reapplied_versions(migrations)
        assert result == set()

    def test_not_reapplied_when_undone_again_after_reapply(self, service):
        # V1 stays applied throughout; V2 goes apply -> undo -> reapply -> undo.
        # The latest event for V2 is the second undo, so it must NOT be
        # considered reapplied even though an earlier reapply exists.
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="2", type="SQL", success=True, installed_rank=2),
            make_migration(version="2", type="UNDO_SQL", success=True, installed_rank=3),
            make_migration(version="2", type="SQL", success=True, installed_rank=4),
            make_migration(version="2", type="UNDO_SQL", success=True, installed_rank=5),
        ]
        result = service._get_reapplied_versions(migrations)
        assert result == set()


# ---------- _is_version_reapplied / _get_undo_rank ----------


@pytest.mark.unit
class TestIsVersionReapplied:
    def test_reapplied_when_sql_rank_higher_than_undo(self, service):
        migrations = [
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=2),
            make_migration(version="1", type="SQL", success=True, installed_rank=3),
        ]
        assert service._is_version_reapplied(migrations, "1") is True

    def test_not_reapplied_when_no_undo(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
        ]
        assert service._is_version_reapplied(migrations, "1") is False

    def test_not_reapplied_when_sql_rank_lower(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=5),
        ]
        assert service._is_version_reapplied(migrations, "1") is False


@pytest.mark.unit
class TestGetUndoRank:
    def test_returns_rank_of_successful_undo(self, service):
        migrations = [
            make_migration(version="1", type="UNDO_SQL", success=True, installed_rank=7),
        ]
        assert service._get_undo_rank(migrations, "1") == 7

    def test_returns_minus_one_when_no_undo(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
        ]
        assert service._get_undo_rank(migrations, "1") == -1

    def test_ignores_failed_undo(self, service):
        migrations = [
            make_migration(version="1", type="UNDO_SQL", success=False, installed_rank=3),
        ]
        assert service._get_undo_rank(migrations, "1") == -1

    def test_returns_latest_rank_when_undone_more_than_once(self, service):
        # undo, reapply, undo again -- must return the latest undo's rank (5),
        # not the first one found (3).
        migrations = [
            make_migration(version="2", type="SQL", success=True, installed_rank=2),
            make_migration(version="2", type="UNDO_SQL", success=True, installed_rank=3),
            make_migration(version="2", type="SQL", success=True, installed_rank=4),
            make_migration(version="2", type="UNDO_SQL", success=True, installed_rank=5),
        ]
        assert service._get_undo_rank(migrations, "2") == 5


# ---------- _get_baseline_version ----------


@pytest.mark.unit
class TestGetBaselineVersion:
    def test_returns_first_baseline(self, service):
        migrations = [
            make_migration(version="1", type="BASELINE", installed_rank=1),
            make_migration(version="2", type="SQL", installed_rank=2),
        ]
        assert service._get_baseline_version(migrations) == "1"

    def test_no_baseline_returns_none(self, service):
        migrations = [
            make_migration(version="1", type="SQL", installed_rank=1),
        ]
        assert service._get_baseline_version(migrations) is None

    def test_empty_list(self, service):
        assert service._get_baseline_version([]) is None


# ---------- _detect_out_of_order_migrations ----------


@pytest.mark.unit
class TestDetectOutOfOrderMigrations:
    def test_in_order_returns_empty(self, service):
        migrations = [
            make_migration(version="1", type="SQL", installed_rank=1),
            make_migration(version="2", type="SQL", installed_rank=2),
            make_migration(version="3", type="SQL", installed_rank=3),
        ]
        assert service._detect_out_of_order_migrations(migrations) == set()

    def test_out_of_order_detected(self, service):
        migrations = [
            make_migration(version="1", type="SQL", installed_rank=1),
            make_migration(version="3", type="SQL", installed_rank=2),
            make_migration(version="2", type="SQL", installed_rank=3),
        ]
        result = service._detect_out_of_order_migrations(migrations)
        assert "2" in result

    def test_skips_non_sql(self, service):
        migrations = [
            make_migration(version="1", type="SQL", installed_rank=1),
            make_migration(version=None, type="REPEATABLE", installed_rank=2),
            make_migration(version="2", type="SQL", installed_rank=3),
        ]
        assert service._detect_out_of_order_migrations(migrations) == set()

    def test_multipart_versions(self, service):
        migrations = [
            make_migration(version="1_1", type="SQL", installed_rank=1),
            make_migration(version="2_0", type="SQL", installed_rank=2),
            make_migration(version="1_2", type="SQL", installed_rank=3),
        ]
        result = service._detect_out_of_order_migrations(migrations)
        assert "1_2" in result


# ---------- _sort_applied_migrations ----------


@pytest.mark.unit
class TestSortAppliedMigrations:
    def test_sorted_by_installed_rank(self, service):
        m1 = make_migration(version="1", installed_rank=3)
        m2 = make_migration(version="2", installed_rank=1)
        m3 = make_migration(version="3", installed_rank=2)
        result = service._sort_applied_migrations([m1, m2, m3])
        assert [m.installed_rank for m in result] == [1, 2, 3]


# ---------- _get_current_version ----------


@pytest.mark.unit
class TestGetCurrentVersion:
    def test_returns_highest_successful_sql(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="3", type="SQL", success=True, installed_rank=2),
            make_migration(version="2", type="SQL", success=True, installed_rank=3),
        ]
        assert service._get_current_version(migrations) == "3"

    def test_ignores_failed(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version="2", type="SQL", success=False, installed_rank=2),
        ]
        assert service._get_current_version(migrations) == "1"

    def test_ignores_non_sql(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
            make_migration(version=None, type="REPEATABLE", success=True, installed_rank=2),
        ]
        assert service._get_current_version(migrations) == "1"

    def test_empty_returns_none(self, service):
        assert service._get_current_version([]) is None


# ---------- _build_analysis_context ----------


@pytest.mark.unit
class TestBuildAnalysisContext:
    def test_returns_all_context_keys(self, service):
        migrations = [
            make_migration(version="1", type="SQL", success=True, installed_rank=1),
        ]
        ctx = service._build_analysis_context(migrations)
        expected_keys = {
            "undone_versions",
            "reapplied_versions",
            "baseline_version",
            "out_of_order_migrations",
            "current_version",
            "target_version",
            "scripts_dir",
        }
        assert set(ctx.keys()) == expected_keys

    def test_includes_target_version_and_scripts_dir(self, service):
        ctx = service._build_analysis_context([])
        assert ctx["target_version"] == "5"
        assert ctx["scripts_dir"] == Path("/tmp/scripts")


# ---------- Constructor ----------


@pytest.mark.unit
class TestConstructor:
    def test_stores_attributes(self, logger):
        svc = MigrationDataService(logger, scripts_dir=Path("/scripts"), target_version="3")
        assert svc.logger is logger
        assert svc.scripts_dir == Path("/scripts")
        assert svc.target_version == "3"

    def test_defaults(self, logger):
        svc = MigrationDataService(logger)
        assert svc.scripts_dir is None
        assert svc.target_version is None

    def test_state_service_created(self, logger):
        svc = MigrationDataService(logger)
        assert isinstance(svc.state_service, MigrationStateService)
