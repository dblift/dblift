"""Regression tests for Flyway/Dblift schema history compatibility checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.sql_validator._flyway_compatibility import validate_flyway_compatibility
from dblift.core.sql_validator.migration_validator import MigrationValidator


def _make_validator(provider: MagicMock) -> MigrationValidator:
    from dblift.core.logger import NullLog
    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
    from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
    from dblift.db.base_quirks import BaseQuirks

    provider.get_schema_qualified_name.return_value = "public.dblift_schema_history"
    provider.get_normalized_object_name.side_effect = lambda name: name
    provider.quirks = BaseQuirks()
    history = MigrationHistoryManager(provider, "public", "tester", NullLog())
    return MigrationValidator(
        MigrationScriptManager(NullLog()), history, NullLog(), quirks=BaseQuirks()
    )


def _row(
    version: str = "1",
    script: str = "V1__init.sql",
    checksum: int = 123,
) -> dict[str, object]:
    return {
        "version": version,
        "description": "init",
        "type": "SQL",
        "script": script,
        "checksum": checksum,
        "installed_by": "tester",
        "installed_rank": 1,
        "success": True,
    }


@pytest.mark.unit
@pytest.mark.parametrize("quirks_path", ["oracle", "db2"])
def test_uppercase_folding_dialect_reads_flyway_quoted_lowercase_table(quirks_path):
    """Oracle and DB2: Flyway's table is ``"flyway_schema_history"`` with
    quoted lowercase columns. The snapshot must find it and read its rows."""
    from dblift.db.provider_registry import ProviderRegistry

    provider = MagicMock()
    provider.quirks = ProviderRegistry.get_quirks(quirks_path)
    existing = {'"flyway_schema_history"', "DBLIFT_SCHEMA_HISTORY"}
    provider.table_exists.side_effect = lambda schema, table: table in existing
    provider.get_schema_qualified_name.side_effect = (
        lambda schema, table: f'"{schema}"."{table.strip(chr(34))}"'
    )
    provider.execute_query.side_effect = [[_row()], [_row()]]
    provider.get_applied_migrations.return_value = [_row()]
    provider.get_normalized_object_name.side_effect = str.upper
    history = MigrationHistoryManager(provider, "APP", "tester", NullLog())

    snapshot = history.collect_flyway_compatibility_snapshot()

    assert snapshot.collection_error == ""
    assert snapshot.flyway_exists is True
    assert [row["script"] for row in snapshot.flyway_migrations] == ["V1__init.sql"]
    flyway_query = provider.execute_query.call_args_list[0].args[0]
    assert flyway_query == 'SELECT * FROM "APP"."flyway_schema_history"'
    # dblift's own history is read the way import-flyway reads it.
    provider.get_applied_migrations.assert_called_once_with("APP", "DBLIFT_SCHEMA_HISTORY")
    assert [row["script"] for row in snapshot.dblift_migrations] == ["V1__init.sql"]
    assert validate_flyway_compatibility(snapshot)["compatible"] is True


@pytest.mark.unit
class TestFlywayCompatibilityCache:
    def test_first_call_computes_instead_of_returning_empty_cache(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], []]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["flyway_exists"] is True
        assert result["Dblift_exists"] is True
        assert result["compatible"] is False
        assert result["flyway_count"] == 1
        assert result["Dblift_count"] == 0
        assert "Flyway has 1 migrations" in str(result["error_message"])
        assert provider.execute_query.call_count == 2

    def test_computed_result_is_cached_after_first_check(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [_row()]]
        validator = _make_validator(provider)

        first = validator.validate_flyway_compatibility()
        second = validator.validate_flyway_compatibility()

        assert first == second
        assert first["compatible"] is True
        assert provider.table_exists.call_count == 2
        assert provider.execute_query.call_count == 2


@pytest.mark.unit
class TestFlywayCompatibilityHistoryColumns:
    def test_dblift_query_uses_script_column(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [_row()]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True
        dblift_query = provider.execute_query.call_args_list[1].args[0]
        assert "script_name" not in dblift_query
        assert "script," in dblift_query
        assert "checksum" in dblift_query

    def test_checksum_mismatch_is_incompatible(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row(checksum=123)], [_row(checksum=456)]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "checksum mismatch" in str(result["error_message"])

    def test_unsigned_and_signed_crc32_values_match(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [
            [_row(checksum=3272252829)],
            [_row(checksum=-1022714467)],
        ]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True

    def test_check_flyway_history_table_propagates_incompatibility(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True, True, True]
        provider.execute_query.side_effect = [[_row()], []]

        result = _make_validator(provider).check_flyway_history_table()

        assert result.success is False
        assert "Flyway has 1 migrations" in result.error_message


@pytest.mark.unit
class TestFlywayCompatibilityAcceptedTypes:
    """The two sides of the type gate accept different vocabularies.

    A dblift history legitimately contains ``PYTHON`` rows — that is what a
    versioned ``.py`` migration is stored as. Flyway has no such type and never
    writes one, so widening both sides would weaken a real check.
    """

    def test_dblift_python_row_is_compatible(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [{**_row(), "type": "PYTHON"}]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True, result["error_message"]

    def test_flyway_python_row_is_still_rejected(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[{**_row(), "type": "PYTHON"}], [_row()]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "Unsupported migration type" in str(result["error_message"])

    def test_dblift_unknown_row_is_still_rejected(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [{**_row(), "type": "NONSENSE"}]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "Migration type mismatch" in str(result["error_message"])


def _imported_history(flyway_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """The dblift rows import-flyway writes for ``flyway_rows``."""
    from dblift.core.migration.commands.import_flyway_command import ImportFlywayCommand

    command = ImportFlywayCommand.__new__(ImportFlywayCommand)
    return [command._row_with_mapped_type(row) for row in flyway_rows]


def _compare(flyway_rows, dblift_rows):
    from dblift.core.migration.history.migration_history_manager import (
        FlywayCompatibilitySnapshot,
    )

    snapshot = FlywayCompatibilitySnapshot(True, True, tuple(flyway_rows), tuple(dblift_rows))
    return validate_flyway_compatibility(snapshot)


@pytest.mark.unit
class TestFlywayCompatibilityAfterImport:
    """A history import-flyway just wrote must read back as compatible."""

    @pytest.mark.parametrize(
        ("flyway_type", "version", "script"),
        [
            ("SQL", "1", "V1__init.sql"),
            ("SQL", None, "R__view.sql"),
            ("JDBC", "2", "db.migration.V2__java"),
            ("JDBC", None, "db.migration.R__java"),
            ("SPRING_JDBC", "3", "db.migration.V3__spring"),
            ("SCRIPT", "4", "V4__script.sh"),
            ("BASELINE", "5", "<< Flyway Baseline >>"),
            ("UNDO_SQL", "5", "U5__init.sql"),
            ("UNDO_SCRIPT", "5", "U5__init.sql"),
            ("DELETE", "6", "V6__gone.sql"),
        ],
    )
    def test_imported_row_is_compatible(self, flyway_type, version, script):
        flyway_rows = [{**_row(version=version, script=script), "type": flyway_type}]

        result = _compare(flyway_rows, _imported_history(flyway_rows))

        assert result["compatible"] is True, result["error_message"]

    def test_mixed_history_with_repeatable_is_compatible(self):
        flyway_rows = [
            _row(version="1", script="V1__init.sql"),
            _row(version="2", script="V2__more.sql"),
            {**_row(version=None, script="R__view.sql"), "installed_rank": 3},
        ]
        dblift_rows = _imported_history(flyway_rows)
        assert dblift_rows[2]["type"] == "REPEATABLE"

        result = _compare(flyway_rows, dblift_rows)

        assert result["compatible"] is True, result["error_message"]

    def test_python_versioned_row_stands_in_for_versioned_flyway_row(self):
        result = _compare([_row()], [{**_row(), "type": "PYTHON"}])

        assert result["compatible"] is True, result["error_message"]

    @pytest.mark.parametrize(
        ("flyway_row", "dblift_type"),
        [
            (_row(), "REPEATABLE"),
            (_row(), "BASELINE"),
            (_row(version=None, script="R__view.sql"), "SQL"),
            (_row(version=None, script="R__view.sql"), "PYTHON"),
            ({**_row(), "type": "BASELINE"}, "SQL"),
            ({**_row(), "type": "UNDO_SQL"}, "SQL"),
        ],
    )
    def test_mismatched_type_is_incompatible(self, flyway_row, dblift_type):
        result = _compare([flyway_row], [{**flyway_row, "type": dblift_type}])

        assert result["compatible"] is False
        assert str(result["error_message"]).startswith("Migration type mismatch at position 1:")
        assert str(result["error_message"]).endswith(f"vs Dblift type '{dblift_type}'.")


@pytest.mark.unit
def test_error_messages_have_no_placeholder_punctuation():
    messages = [
        _compare([_row()], [])["error_message"],
        _compare([_row()], [_row(version="2")])["error_message"],
        _compare([{**_row(), "type": "PYTHON"}], [_row()])["error_message"],
        _compare([_row()], [{**_row(), "type": "NONSENSE"}])["error_message"],
        _compare([_row()], [_row(script="V1__other.sql")])["error_message"],
        _compare([_row()], [_row(checksum=9)])["error_message"],
    ]
    from dblift.core.migration.history.migration_history_manager import (
        FlywayCompatibilitySnapshot,
    )
    from dblift.core.sql_validator._flyway_compatibility import check_flyway_history_table

    messages.append(
        check_flyway_history_table(
            FlywayCompatibilitySnapshot(flyway_exists=True, dblift_exists=False)
        ).error_message
    )
    for message in messages:
        assert message and ". ." not in message and ".  ." not in message
        assert message.strip() != "."
    assert "import-flyway" in messages[-1]


def test_state_read_phase_caches_data_and_new_phase_refreshes():
    provider = MagicMock()
    provider.table_exists.return_value = True
    provider.execute_query.side_effect = [[_row()], [_row()], [_row()], []]
    validator = _make_validator(provider)
    manager = validator.state_manager
    snapshot = manager.get_flyway_compatibility_snapshot()
    with pytest.raises(TypeError):
        snapshot.flyway_migrations[0]["version"] = "changed"
    first = validator.validate_flyway_compatibility()
    first["compatible"] = False
    assert validator.validate_flyway_compatibility()["compatible"] is True
    assert provider.execute_query.call_count == 2
    manager.new_read_snapshot()
    assert validator.validate_flyway_compatibility()["compatible"] is False
    assert provider.execute_query.call_count == 4


def test_legacy_table_check_creates_history_through_state_manager():
    provider = MagicMock()
    provider.table_exists.return_value = False
    validator = _make_validator(provider)
    history = validator.state_manager.history_manager
    from unittest.mock import patch

    with patch.object(history, "create_schema_and_history_table") as create:
        validator._check_table_compatibility([])
    create.assert_called_once_with()


def test_history_check_preserves_compatibility_query_error_message():
    provider = MagicMock()
    provider.table_exists.return_value = True
    provider.execute_query.side_effect = RuntimeError("history unavailable")
    result = _make_validator(provider).check_flyway_history_table()
    assert not result.success
    assert result.error_message == "Error checking Flyway compatibility: history unavailable"


@pytest.mark.parametrize("side", ["flyway", "dblift"])
@pytest.mark.parametrize("bad_type", [None, 17])
@pytest.mark.parametrize(
    "entrypoint", ["pure", "validate_flyway_compatibility", "check_flyway_history_table"]
)
def test_malformed_row_types_return_compatibility_errors(side, bad_type, entrypoint):
    provider = MagicMock()
    provider.table_exists.return_value = True
    flyway_row, dblift_row = _row(), _row()
    (flyway_row if side == "flyway" else dblift_row)["type"] = bad_type
    provider.execute_query.side_effect = [[flyway_row], [dblift_row]]
    validator = _make_validator(provider)
    if entrypoint == "pure":
        from dblift.core.sql_validator._flyway_compatibility import validate_flyway_compatibility

        result = validate_flyway_compatibility(
            validator.state_manager.get_flyway_compatibility_snapshot()
        )
    else:
        result = getattr(validator, entrypoint)()
    expected = f"Error checking Flyway compatibility: '{type(bad_type).__name__}' object has no attribute 'upper'"
    if entrypoint == "check_flyway_history_table":
        assert result.success is False
        assert result.error_message == expected
    else:
        assert result["compatible"] is False
        assert result["error_message"] == expected
        assert result["flyway_count"] == result["Dblift_count"] == 1
