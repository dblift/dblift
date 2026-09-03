"""The migration-version naming convention, pinned in one place.

A version must start with a digit. That single rule decides three things
that used to be decided inconsistently:

* ``VA__create.sql`` is **not** a migration. Flyway has never supported
  letter versions (``MigrationVersion`` stores ``List<BigInteger>`` and
  rejects any non-numeric token), and accepting them is undecidable
  against ordinary filenames: ``VA__x.sql`` and ``Users__seed.sql`` have
  the same shape, so ``Users__seed.sql`` would become version ``sers``.
* ``V3.2A__create.sql`` **is** a migration. dblift is deliberately looser
  than Flyway here — only the *leading* character must be a digit — and
  this is long-standing accepted behaviour.
* ``Migration._determine_type`` and ``MigrationScriptManager.parse_filename``
  agree. They used to disagree in both directions, and the stricter one
  silently won.

Anything that looks like it was meant to be a migration but does not parse
must be reported, never dropped in silence.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager


def _manager() -> MigrationScriptManager:
    return MigrationScriptManager(logger=MagicMock())


ACCEPTED = [
    ("V1__create.sql", MigrationType.SQL, "1"),
    ("V1.2.3__create.sql", MigrationType.SQL, "1.2.3"),
    ("V1_2_3__create.sql", MigrationType.SQL, "1.2.3"),
    ("V3.2A__create.sql", MigrationType.SQL, "3.2A"),
    ("V1.2.3RC1__create.sql", MigrationType.SQL, "1.2.3RC1"),
    # Underscores are rewritten to dots only when the version is all digits.
    # A lettered version keeps its separators verbatim, so it still matches
    # the string already recorded in existing history rows.
    ("V1_2A__create.sql", MigrationType.SQL, "1_2A"),
    ("V1_2_3RC1__create.sql", MigrationType.SQL, "1_2_3RC1"),
    ("U1__undo.sql", MigrationType.UNDO_SQL, "1"),
    ("U1.2__undo.sql", MigrationType.UNDO_SQL, "1.2"),
]

# Same shape as a letter version — which is exactly why letter versions
# cannot be supported: no rule separates these two columns.
REJECTED = [
    "VA__create.sql",
    "VB__create.sql",
    "UA__undo.sql",
    "Users__seed.sql",
    "Update__rows.sql",
    "Validate__schema.sql",
]


@pytest.mark.unit
class TestAcceptedVersions:
    @pytest.mark.parametrize("filename, expected_type, expected_version", ACCEPTED)
    def test_parse_filename(self, filename, expected_type, expected_version):
        migration_type, version, _, _ = _manager().parse_filename(filename)
        assert migration_type == expected_type
        assert version == expected_version

    @pytest.mark.parametrize("filename, expected_type, expected_version", ACCEPTED)
    def test_classifiers_agree(self, filename, expected_type, expected_version):
        parsed_type, _, _, _ = _manager().parse_filename(filename)
        assert Migration(script_name=filename, content="SELECT 1;").type == parsed_type


@pytest.mark.unit
class TestRejectedVersions:
    @pytest.mark.parametrize("filename", REJECTED)
    def test_parse_filename_rejects(self, filename):
        migration_type, version, _, _ = _manager().parse_filename(filename)
        assert migration_type == MigrationType.UNKNOWN
        assert version is None, f"{filename} must not yield a version, got {version!r}"

    @pytest.mark.parametrize("filename", REJECTED)
    def test_classifiers_agree(self, filename):
        assert Migration(script_name=filename, content="SELECT 1;").type == MigrationType.UNKNOWN

    @pytest.mark.parametrize("filename", REJECTED)
    def test_loader_excludes(self, tmp_path: Path, filename: str):
        (tmp_path / filename).write_text("SELECT 1;")
        loaded = [m.script_name for m in _manager().get_migration_scripts(tmp_path)]
        assert filename not in loaded


@pytest.mark.unit
class TestInvalidNamesAreReported:
    """A near-miss must be loud; an ordinary helper file must stay quiet."""

    def _warnings(self, tmp_path: Path) -> str:
        manager = _manager()
        manager.get_migration_scripts(tmp_path)
        return " ".join(str(call) for call in manager.logger.warning.call_args_list)

    @pytest.mark.parametrize(
        "filename",
        [
            "V2.1_create.sql",  # single underscore — the classic typo
            "VA__create.sql",
            "U3_undo.sql",
            "R_repeat.sql",
        ],
    )
    def test_migration_shaped_name_is_warned_about(self, tmp_path: Path, filename: str):
        (tmp_path / filename).write_text("SELECT 1;")
        assert filename in self._warnings(tmp_path)

    @pytest.mark.parametrize(
        "filename",
        [
            "__init__.py",
            "helpers.py",
            "notes.sql",
            "seed_data.sql",
            # Start with a migration prefix letter but are plainly not
            # attempts at the convention. The prefix alone must not warn.
            "backup_old.sql",
            "routines.sql",
            "users.sql",
            "views.sql",
            "utils.py",
            # Prefix letter *and* a '__' separator, but the character after
            # the prefix is an ordinary letter — these are words, not versions.
            "util__helpers.py",
            "report__daily.sql",
            "views__all.sql",
            "user__roles.sql",
        ],
    )
    def test_ordinary_file_is_not_warned_about(self, tmp_path: Path, filename: str):
        (tmp_path / "V1__real.sql").write_text("SELECT 1;")
        (tmp_path / filename).write_text("SELECT 1;\n")
        assert filename not in self._warnings(tmp_path)

    def test_valid_migrations_produce_no_warning(self, tmp_path: Path):
        (tmp_path / "V1__create.sql").write_text("SELECT 1;")
        (tmp_path / "R__refresh.sql").write_text("SELECT 1;")
        assert self._warnings(tmp_path) == ""
