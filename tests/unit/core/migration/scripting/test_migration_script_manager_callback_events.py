"""Unit tests for callback event matching in ``MigrationScriptManager``.

``get_callbacks_by_event()`` selected callback files with a bare ``startswith()``
on the event prefix. Five prefixes in ``_CALLBACK_PREFIXES`` are literal
substrings of other prefixes in the same list, so a file named with the longer
prefix also matched the shorter event:

    afterMigrate ⊂ afterMigrateError
    beforeEach   ⊂ beforeEachMigrate
    afterEach    ⊂ afterEachMigrate
    afterClean   ⊂ afterCleanError
    afterUndo    ⊂ afterUndoError

Two observable consequences:

1. ``afterMigrateError__notify.sql`` ran on a fully successful ``migrate``,
   because ``afterMigrate`` is a prefix of ``afterMigrateError``. Alerting or
   compensating SQL fired when nothing had failed.
2. ``beforeEachMigrate__mark.sql`` ran twice per script — ``MigrateCommand``
   dispatches ``beforeEach`` and ``beforeEachMigrate`` as two distinct events
   and the file matched both.

Callback names are ``<eventPrefix>__<description>.<ext>``. The ``__``
separator is mandatory: matching requires it right after the prefix, and a
name that starts with a callback prefix without it is not a callback at all.
"""

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from core.migration.migration import _CALLBACK_PREFIXES, Migration, MigrationType
from core.migration.scripting.migration_script_manager import MigrationScriptManager

pytestmark = [pytest.mark.unit]


# (shorter prefix, longer prefix that starts with it)
COLLIDING_PREFIX_PAIRS = [
    ("afterMigrate", "afterMigrateError"),
    ("beforeEach", "beforeEachMigrate"),
    ("afterEach", "afterEachMigrate"),
    ("afterClean", "afterCleanError"),
    ("afterUndo", "afterUndoError"),
]


def _manager() -> MigrationScriptManager:
    return MigrationScriptManager(MagicMock())


def _names(callbacks: List) -> List[str]:
    return [Path(cb.script_name).name for cb in callbacks]


def test_colliding_prefix_pairs_list_is_complete():
    """The pairs exercised below are exactly the collisions in _CALLBACK_PREFIXES.

    Guards the test data itself: a new prefix that is a substring of another one
    must be added here, or the boundary regression it enables goes untested.
    """
    actual = {
        (short, long)
        for short in _CALLBACK_PREFIXES
        for long in _CALLBACK_PREFIXES
        if short != long and long.lower().startswith(short.lower())
    }

    assert actual == set(COLLIDING_PREFIX_PAIRS)


@pytest.mark.parametrize("short_prefix,long_prefix", COLLIDING_PREFIX_PAIRS)
def test_longer_prefix_callback_does_not_match_shorter_event(
    tmp_path: Path, short_prefix: str, long_prefix: str
):
    """A file named with the longer prefix must not be selected for the shorter event."""
    (tmp_path / f"{long_prefix}__notify.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, short_prefix, recursive=False)

    assert _names(callbacks) == []


@pytest.mark.parametrize("short_prefix,long_prefix", COLLIDING_PREFIX_PAIRS)
def test_each_callback_matches_exactly_one_of_a_colliding_pair(
    tmp_path: Path, short_prefix: str, long_prefix: str
):
    """Both files present: each event selects only its own file, once.

    This is the double-execution symptom. ``MigrateCommand`` calls
    ``get_callbacks_by_event`` once per event name, so a file matching both
    names is executed twice per migration script.
    """
    (tmp_path / f"{short_prefix}__mark.sql").write_text("SELECT 1;")
    (tmp_path / f"{long_prefix}__mark.sql").write_text("SELECT 2;")

    manager = _manager()
    short_matches = manager.get_callbacks_by_event(tmp_path, short_prefix, recursive=False)
    long_matches = manager.get_callbacks_by_event(tmp_path, long_prefix, recursive=False)

    assert _names(short_matches) == [f"{short_prefix}__mark.sql"]
    assert _names(long_matches) == [f"{long_prefix}__mark.sql"]


def test_error_callback_is_not_selected_for_the_success_event(tmp_path: Path):
    """The safety-critical case: afterMigrateError must not run on a successful migrate."""
    (tmp_path / "afterMigrate__finalize.sql").write_text("SELECT 1;")
    (tmp_path / "afterMigrateError__notify.sql").write_text("SELECT 2;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)

    assert _names(callbacks) == ["afterMigrate__finalize.sql"]


@pytest.mark.parametrize("prefix", _CALLBACK_PREFIXES)
def test_described_callback_still_matches_its_own_event(tmp_path: Path, prefix: str):
    """``<prefix>__<description>.sql`` must still be selected for ``<prefix>``."""
    (tmp_path / f"{prefix}__do_it.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, prefix, recursive=False)

    assert _names(callbacks) == [f"{prefix}__do_it.sql"]


@pytest.mark.parametrize("prefix", _CALLBACK_PREFIXES)
def test_description_less_name_matches_no_event(tmp_path: Path, prefix: str):
    """``<prefix>.sql`` has no ``__`` separator, so it is not a callback.

    The documented convention is ``<eventPrefix>__<description>.<ext>``; the
    description is not optional.
    """
    (tmp_path / f"{prefix}.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, prefix, recursive=False)

    assert _names(callbacks) == []


def test_event_matching_stays_case_insensitive(tmp_path: Path):
    """Case-insensitive matching predates this fix and must survive it."""
    (tmp_path / "AFTERMIGRATE__finalize.sql").write_text("SELECT 1;")
    (tmp_path / "AFTERMIGRATEERROR__notify.sql").write_text("SELECT 2;")

    manager = _manager()

    assert _names(manager.get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)) == [
        "AFTERMIGRATE__finalize.sql"
    ]
    assert _names(
        manager.get_callbacks_by_event(tmp_path, "afterMigrateError", recursive=False)
    ) == ["AFTERMIGRATEERROR__notify.sql"]


def test_single_underscore_is_not_a_delimiter(tmp_path: Path):
    """``afterMigrate_notify.sql`` does not use the ``__`` separator."""
    (tmp_path / "afterMigrate_notify.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)

    assert _names(callbacks) == []


# --- Classification: a name without ``__`` is not a callback at all ----------


MALFORMED_CALLBACK_NAMES = [
    "afterMigrate.sql",
    "afterMigrate_notify.sql",
    "beforeEachMigrate.sql",
    "afterMigrateError.py",
    "AFTERCLEAN.sql",
]


@pytest.mark.parametrize("filename", MALFORMED_CALLBACK_NAMES)
def test_parse_filename_does_not_classify_a_delimiterless_name_as_callback(filename: str):
    """``parse_filename`` must not report CALLBACK without the ``__`` separator."""
    migration_type, _, _, _ = _manager().parse_filename(filename)

    assert migration_type is not MigrationType.CALLBACK


@pytest.mark.parametrize("filename", MALFORMED_CALLBACK_NAMES)
def test_delimiterless_name_is_not_a_valid_script_name(filename: str):
    """Discovery must reject the name outright, like any other malformed script."""
    assert _manager().is_valid_script_name(filename) is False


@pytest.mark.parametrize("filename", MALFORMED_CALLBACK_NAMES)
def test_migration_type_does_not_classify_a_delimiterless_name_as_callback(filename: str):
    """``Migration._determine_type`` must agree with ``parse_filename``.

    The model and the script manager are consulted by different call sites
    (the validator reads ``Migration.type``); one answering CALLBACK while the
    other rejects the file is how a script ends up loaded but never run.
    """
    assert Migration(script_name=filename).type is not MigrationType.CALLBACK


@pytest.mark.parametrize("filename", MALFORMED_CALLBACK_NAMES)
def test_delimiterless_name_is_not_loaded_as_a_callback(tmp_path: Path, filename: str):
    """End of the loader path: the file lands in no migration bucket."""
    (tmp_path / filename).write_text("SELECT 1;")

    migrations = _manager().load_migration_scripts(tmp_path, recursive=False)

    assert all(loaded == [] for loaded in migrations.values())


def test_delimiterless_callback_name_is_reported_as_a_naming_violation(tmp_path: Path):
    """Rejection must be visible, not silent.

    A file named for a callback event but missing ``__`` is a typo the user
    needs told about — otherwise it sits in the migrations directory looking
    like a callback and never runs.
    """
    (tmp_path / "afterMigrate.sql").write_text("SELECT 1;")
    logger = MagicMock()

    MigrationScriptManager(logger).load_migration_scripts(tmp_path, recursive=False)

    warnings = " ".join(str(call) for call in logger.warning.call_args_list)
    assert "afterMigrate.sql" in warnings
    assert "naming convention" in warnings


def test_naming_violation_is_reported_once_per_manager(tmp_path: Path):
    """``get_callbacks_by_event`` reloads the directory for every event.

    A migrate dispatches a dozen events, so a per-load warning would repeat the
    same filename a dozen times in one run.
    """
    (tmp_path / "afterMigrate.sql").write_text("SELECT 1;")
    logger = MagicMock()
    manager = MigrationScriptManager(logger)

    for _ in range(3):
        manager.load_migration_scripts(tmp_path, recursive=False)

    reports = [call for call in logger.warning.call_args_list if "afterMigrate.sql" in str(call)]
    assert len(reports) == 1


def test_well_formed_callback_is_not_reported_as_a_violation(tmp_path: Path):
    """No false positives: a correctly named callback warns about nothing."""
    (tmp_path / "afterMigrate__finalize.sql").write_text("SELECT 1;")
    logger = MagicMock()

    MigrationScriptManager(logger).load_migration_scripts(tmp_path, recursive=False)

    assert logger.warning.call_args_list == []


# --- Tags: matching must normalize the name the same way classification does --


# ``parse_filename`` strips a ``[...]`` group with a positionless regex, so it
# accepts tags anywhere in the name, not only in the documented
# ``<prefix>__<description>[tag1,tag2].<ext>`` position. Event matching has to
# accept every position classification does, or the file is filed as a callback
# and then dispatched to nothing.
TAGGED_CALLBACK_NAMES = [
    "afterMigrate__notify[prod].sql",  # documented position
    "afterMigrate[prod]__notify.sql",  # between prefix and separator
    "[prod]afterMigrate__notify.sql",  # leading
    "afterMigrate[prod,eu]__notify.sql",  # multiple tags
]


@pytest.mark.parametrize("filename", TAGGED_CALLBACK_NAMES)
def test_tagged_callback_is_dispatched_to_its_event(tmp_path: Path, filename: str):
    """A tagged callback must reach its event, through the real load path.

    Asserts dispatch rather than the matcher return value: the failure this
    guards against is classification and matching disagreeing, which only shows
    up when both run.
    """
    (tmp_path / filename).write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)

    assert _names(callbacks) == [filename]


@pytest.mark.parametrize("filename", TAGGED_CALLBACK_NAMES)
def test_tagged_callback_does_not_reach_a_colliding_event(tmp_path: Path, filename: str):
    """Stripping tags must not reopen the prefix collision."""
    tagged_error_callback = filename.replace("afterMigrate", "afterMigrateError")
    (tmp_path / tagged_error_callback).write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)

    assert _names(callbacks) == []


@pytest.mark.parametrize("filename", TAGGED_CALLBACK_NAMES)
def test_tagged_callback_type_agrees_between_model_and_manager(filename: str):
    """``Migration.type`` and ``parse_filename`` must not disagree about tags."""
    assert Migration(script_name=filename).type is MigrationType.CALLBACK
    assert _manager().parse_filename(filename)[0] is MigrationType.CALLBACK


MALFORMED_TAGGED_NAMES = [
    "afterMigrate[prod]notify.sql",  # tags, but no separator anywhere
    "afterMigrate[prod].sql",  # tags standing in for the description
    "afterMigrate[prod]_notify.sql",  # single underscore
]


@pytest.mark.parametrize("filename", MALFORMED_TAGGED_NAMES)
def test_malformed_tagged_name_is_rejected_and_reported(tmp_path: Path, filename: str):
    """Tags must not smuggle a separator-less name past the naming check."""
    (tmp_path / filename).write_text("SELECT 1;")
    logger = MagicMock()
    manager = MigrationScriptManager(logger)

    migrations = manager.load_migration_scripts(tmp_path, recursive=False)

    assert all(loaded == [] for loaded in migrations.values())
    warnings = " ".join(str(call) for call in logger.warning.call_args_list)
    assert filename in warnings
    assert "naming convention" in warnings


# --- The invariant the tag bug violated --------------------------------------


AGREEMENT_SAMPLE = (
    TAGGED_CALLBACK_NAMES
    + MALFORMED_TAGGED_NAMES
    + MALFORMED_CALLBACK_NAMES
    + [
        "afterMigrate__notify.sql",
        "afterMigrateError__notify.sql",
        "beforeEachMigrate__mark.py",
        "AFTERMIGRATE__SHOUTING.sql",
        "V1__not_a_callback.sql",
        "R__not_a_callback.sql",
    ]
)


@pytest.mark.parametrize("filename", AGREEMENT_SAMPLE)
def test_a_file_classified_as_a_callback_always_reaches_an_event(tmp_path: Path, filename: str):
    """Classification and matching must never disagree.

    Every file the loader files under CALLBACK must be dispatched by exactly
    one event, and nothing else may be. When the two paths normalize names
    differently — as they did for tags — a file lands in the callback bucket
    and is then dispatched to no event: it never runs, and because it is a
    *valid* script name it draws no naming-convention warning either. Silent.
    """
    (tmp_path / filename).write_text("SELECT 1;")
    manager = _manager()

    classified_as_callback = _names(
        manager.load_migration_scripts(tmp_path, recursive=False)[MigrationType.CALLBACK]
    )
    dispatched = [
        name
        for prefix in _CALLBACK_PREFIXES
        for name in _names(manager.get_callbacks_by_event(tmp_path, prefix, recursive=False))
    ]

    assert dispatched == classified_as_callback
