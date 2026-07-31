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

Callback names are ``<eventPrefix>__<description>.<ext>`` or the
description-less ``<eventPrefix>.<ext>``; matching requires one of those two
boundaries right after the prefix.
"""

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from core.migration.migration import _CALLBACK_PREFIXES
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
def test_description_less_callback_still_matches_its_own_event(tmp_path: Path, prefix: str):
    """``<prefix>.sql`` (no description) must still be selected for ``<prefix>``.

    The description is optional, so the extension boundary counts as a
    delimiter too — requiring ``__`` alone would stop these from ever running.
    """
    (tmp_path / f"{prefix}.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, prefix, recursive=False)

    assert _names(callbacks) == [f"{prefix}.sql"]


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
    """``afterMigrate_notify.sql`` does not use the ``__`` separator, so it is not
    an ``afterMigrate`` callback.

    Tradeoff worth naming: such a file is still *classified* as a callback by
    ``parse_filename``, so after this fix it is loaded but dispatched to no
    event. It previously ran on ``afterMigrate``. Both behaviours are silent;
    tightening the classifier as well is a separate change.
    """
    (tmp_path / "afterMigrate_notify.sql").write_text("SELECT 1;")

    callbacks = _manager().get_callbacks_by_event(tmp_path, "afterMigrate", recursive=False)

    assert _names(callbacks) == []
