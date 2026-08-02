"""Regression: validate_checksums must not hard-fail on history rows written
before PR #129 removed directory-qualified script_name.

PR #129 fixed ``load_migration_scripts`` to always store the bare filename in
``Migration.script_name`` for scripts found in a secondary ``--scripts``
directory. But any history row written *before* that fix (any installation
that used ``--scripts``/multi-directory support prior to this PR) still has
the old, directory-qualified value persisted in the ``script`` column (e.g.
``extra-migrations/R__cleanup.sql``), while the freshly-loaded Migration
object now computes the bare filename (``R__cleanup.sql``).

``validate_checksums`` compared the two with no fallback, so an already
applied migration from a secondary directory was reported as "missing from
the migration directory" and ``validate --strict`` hard-failed on it —
recreating, in the opposite direction, the exact "renamed migration" symptom
PR #129 set out to fix.
"""

from unittest.mock import MagicMock

import pytest

from core.logger import NullLog
from core.migration.migration import MigrationType
from core.sql_validator.migration_validator import MigrationValidator, ValidationResult


def _make_validator():
    script_manager = MagicMock()
    history_manager = MagicMock()
    history_manager.provider = MagicMock()
    history_manager.provider.config = None
    log = MagicMock()
    v = MigrationValidator.__new__(MigrationValidator)
    v.script_manager = script_manager
    v.history_manager = history_manager
    v.log = log
    v.placeholders = {}
    from core.migration.sql.sql_analyzer import SqlAnalyzer

    v.sql_analyzer = SqlAnalyzer(dialect="oracle", logger=NullLog())
    v._flyway_compatibility_cache = None
    return v


def _make_migration(script_name, version, migration_type=MigrationType.SQL):
    m = MagicMock()
    m.script_name = script_name
    m.version = version
    m.type = migration_type
    m.success = True
    return m


@pytest.mark.unit
class TestValidateChecksumsLegacyQualifiedHistoryFallback:
    @pytest.mark.parametrize(
        "migration_type,version",
        [
            (MigrationType.REPEATABLE, None),
            (MigrationType.SQL, "2"),
        ],
        ids=["repeatable", "versioned"],
    )
    def test_strict_mode_does_not_hard_fail_on_legacy_qualified_history_row(
        self, migration_type, version
    ):
        """A migration already applied from a secondary directory under the
        old (pre-PR#129) scheme must resolve against its bare-name fresh
        counterpart, not be reported as missing/renamed."""
        validator = _make_validator()

        # Fresh migration loaded from the secondary directory: bare filename (PR #129).
        fresh_script = _make_migration(
            "R__cleanup.sql" if migration_type == MigrationType.REPEATABLE else "V2__cleanup.sql",
            version,
            migration_type=migration_type,
        )
        # History row applied before PR #129: directory-qualified script_name.
        applied = _make_migration(
            (
                "extra-migrations/R__cleanup.sql"
                if migration_type == MigrationType.REPEATABLE
                else "extra-migrations/V2__cleanup.sql"
            ),
            version,
            migration_type=migration_type,
        )

        result = ValidationResult()
        issues = []

        validator._validate_checksums(
            scripts=[fresh_script],
            applied_migrations=[applied],
            result=result,
            issues=issues,
            strict_mode=True,
        )

        assert issues == [], (
            "validate --strict must not hard-fail an already-applied migration whose "
            f"history row predates PR #129's bare-filename fix. Issues: {issues}"
        )
