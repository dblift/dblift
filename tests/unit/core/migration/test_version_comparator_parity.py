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


@pytest.mark.unit
class TestMixedAlphanumericSegments:
    """A segment like ``3RC1`` must order by its leading number first.

    The tokenizer once matched only ``<digits><letters>``, so ``3RC1`` (letters
    then digits again) fell through to the pure-alpha branch — which sorts
    above *every* numeric segment. ``1.2.3RC1`` therefore compared greater than
    ``1.2.4``, which is wrong under any convention.
    """

    @pytest.mark.parametrize(
        "lower, higher",
        [
            ("1.2.3RC1", "1.2.4"),
            ("1.2.3RC1", "1.3.0"),
            ("1.2.3RC1", "1.2.3RC2"),
            ("1.2.9RC1", "1.2.10RC1"),
            ("2.0.0BETA2", "2.0.1"),
        ],
    )
    def test_orders_by_leading_number(self, lower: str, higher: str):
        assert compare_versions(lower, higher) < 0
        assert compare_versions(higher, lower) > 0

    def test_equal_to_itself(self):
        assert compare_versions("1.2.3RC1", "1.2.3RC1") == 0

    @pytest.mark.parametrize(
        "suffixed, bare",
        [("3.2A", "3.2"), ("1.2.3RC1", "1.2.3"), ("2.0.0BETA2", "2.0.0")],
    )
    def test_suffix_sorts_after_the_bare_version(self, suffixed: str, bare: str):
        """Long-standing dblift convention: a suffix is a later revision.

        Deliberately *not* PEP 440, where a suffix marks a pre-release and
        sorts before. Migration suffixes are used as hotfix markers, and the
        ordering has shipped this way — flipping it would silently reorder
        existing histories.
        """
        assert compare_versions(suffixed, bare) > 0
        assert compare_versions(bare, suffixed) < 0
