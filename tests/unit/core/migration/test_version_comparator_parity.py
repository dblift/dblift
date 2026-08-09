"""One comparator for migration versions, everywhere.

``core.migration.version_utils.compare_versions`` is the documented
comparator: it handles letter versions (``VA`` vs ``VB``) and underscore
separators (``1_2_3``). Two other orderings had grown alongside it —
PEP 440 parsing in baseline filtering, which *raises* on both of those
formats, and an int-only parse in out-of-order detection, which collapses
every alpha segment to ``0`` so ``VA == VB``. These tests pin the shared
semantics at both call sites.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.migration.migration import Migration
from core.migration.state.migration_data_service import MigrationDataService
from core.migration.version_utils import compare_versions
from core.sql_validator._migration_filter import handle_baseline_filtering
from core.sql_validator.migration_validator import MigrationValidator


def _validator() -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.log = MagicMock()
    validator.script_manager = SimpleNamespace(compare_versions=compare_versions)
    return validator


def _script(tmp_path: Path, name: str) -> Migration:
    path = tmp_path / name
    path.write_text("SELECT 1;\n")
    return Migration(script_path=path)


def _data_service() -> MigrationDataService:
    service = MigrationDataService.__new__(MigrationDataService)
    service.logger = MagicMock()
    return service


def _applied(version: str) -> SimpleNamespace:
    return SimpleNamespace(version=version, type="SQL", script_name=f"V{version}__x.sql")


@pytest.mark.unit
class TestBaselineFilteringUsesSharedComparator:
    """Baseline pruning must accept every version format the comparator documents."""

    @pytest.mark.parametrize(
        "baseline_version, old_version, new_version",
        [
            ("2", "1", "3"),
            # Underscore separators: PEP 440 rejected "1_2_0" outright.
            ("1_2_0", "1_1_0", "1_3_0"),
        ],
    )
    def test_drops_pre_baseline_and_keeps_later(
        self, tmp_path: Path, baseline_version: str, old_version: str, new_version: str
    ):
        baseline = Migration.create_baseline_migration("-- baseline", baseline_version, "based")
        old = _script(tmp_path, f"V{old_version}__old.sql")
        new = _script(tmp_path, f"V{new_version}__new.sql")

        kept = [
            s.script_name for s in handle_baseline_filtering(_validator(), [baseline, old, new])
        ]

        assert old.script_name not in kept
        assert new.script_name in kept

    def test_version_less_baseline_prunes_nothing(self, tmp_path: Path):
        """A baseline carrying no version defines no cut-off.

        ``MigrationScriptManager`` excludes on-disk baselines, so this list only
        arises when the helper is called directly — but pruning every versioned
        script (or raising) is the wrong answer either way.
        """
        baseline = Migration.create_baseline_migration("-- baseline", "", "based")
        old = _script(tmp_path, "V1__old.sql")

        kept = [s.script_name for s in handle_baseline_filtering(_validator(), [baseline, old])]

        assert old.script_name in kept


@pytest.mark.unit
class TestOutOfOrderDetectionUsesSharedComparator:
    """Out-of-order detection must not collapse alpha segments to zero."""

    def test_detects_numeric_regression(self):
        service = _data_service()
        found = service._detect_out_of_order_migrations([_applied("2"), _applied("1")])
        assert found == {"1"}

    def test_detects_letter_version_regression(self):
        """``VB`` then ``VA`` is out of order; int-parsing scored both as 0."""
        service = _data_service()
        found = service._detect_out_of_order_migrations([_applied("B"), _applied("A")])
        assert found == {"A"}

    def test_in_order_letter_versions_are_clean(self):
        service = _data_service()
        found = service._detect_out_of_order_migrations([_applied("A"), _applied("B")])
        assert found == set()


@pytest.mark.unit
def test_underscore_and_dot_separators_are_equivalent():
    """Guards the property both replaced implementations relied on."""
    assert compare_versions("1_2_3", "1.2.3") == 0
