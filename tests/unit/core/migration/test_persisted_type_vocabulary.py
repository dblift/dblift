"""Freeze the ``MigrationType`` vocabulary that is written to migration history.

This file is a **characterization lock, not a specification of good design**.
Every value it pins is the *legacy* vocabulary: ``MigrationType`` conflates the
*role* of a migration (versioned / repeatable / undo / callback / baseline /
delete) with its *format* (SQL / non-SQL). ``MigrationType.SQL`` does not mean
"a .sql file" — it means "versioned", and ``parse_filename`` returns it for
``.py`` scripts too. ``Migration.__init__`` then rewrites it to ``PYTHON`` when
the detected format is a non-SQL scripted format.

None of that is desirable, and it is deliberately frozen anyway, because the
enum *member name* is what lands in ``dblift_schema_history.type`` and is read
back by name. The read path degrades an unrecognised value to
``MigrationType.UNKNOWN`` **silently**; ``UNKNOWN`` is not versioned, so a
history row that stops round-tripping stops counting as applied, and ``migrate``
re-runs an already-applied script against a live schema. There is no
history-upgrade mechanism that could repair such a database after the fact.

So: a change that makes any assertion here fail is a change to a persisted,
unmigratable wire format. It may still be the right change — but it has to be
made on purpose, with a history-upgrade story, not as a side effect of tidying
the enum.
"""

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from dblift.core.migration._type_match import is_versioned
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import AppliedMigration, Migration, MigrationType

# The persisted vocabulary, spelled out literally rather than derived from
# ``MigrationType`` itself. A parametrization built from ``list(MigrationType)``
# renames and shrinks in lockstep with the enum, so it cannot detect a rename or
# a removed member — see ``test_every_member_name_round_trips_from_history_row``
# below, which does exactly that and passes 35-37/37 whether ``BASELINE`` is
# renamed to ``BASE``, ``CALLBACK`` to ``CB``, or ``DELETE`` is deleted outright.
# This tuple only changes when someone deliberately edits it, so a rename or
# removal in the enum shows up as a mismatch here instead of a silently smaller
# parametrization.
PERSISTED_TYPE_NAMES = (
    "SQL",
    "PYTHON",
    "REPEATABLE",
    "UNDO_SQL",
    "BASELINE",
    "CALLBACK",
    "DELETE",
    "UNKNOWN",
)


class RecordingProvider:
    """Minimal database provider that captures what ``record_migration`` is handed.

    Deliberately an explicit fake rather than a ``MagicMock``: a mock
    auto-creates whatever attribute the code under test touches, so a test
    written against one keeps passing after the production call changes to a
    method that does not exist. This class only has the surface
    ``MigrationHistoryManager.record_migration`` actually uses, so a change to
    that call surfaces as an ``AttributeError`` instead of a false green.
    """

    def __init__(self) -> None:
        self.recorded: List[Tuple[str, Dict[str, Any], str]] = []

    def record_migration(
        self, schema: str, migration_info: Dict[str, Any], history_table: str
    ) -> None:
        self.recorded.append((schema, migration_info, history_table))


def _write(tmp_path: Path, name: str, content: str = "-- noop\n") -> Path:
    script = tmp_path / name
    script.write_text(content, encoding="utf-8")
    return script


# ---------------------------------------------------------------------------
# 1. Types assigned when a Migration is constructed from a path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("V1__x.sql", MigrationType.SQL),
        ("V1__x.py", MigrationType.PYTHON),
        ("R__x.sql", MigrationType.REPEATABLE),
        ("R__x.py", MigrationType.REPEATABLE),
        ("U1__x.sql", MigrationType.UNDO_SQL),
        ("U1__x.py", MigrationType.UNDO_SQL),
    ],
)
def test_path_constructed_migration_type(
    tmp_path: Path, filename: str, expected: MigrationType
) -> None:
    """Pin the type a path-constructed ``Migration`` receives.

    ``script_path`` must be a :class:`pathlib.Path`, not a ``str`` — the
    constructor reads ``script_path.name``.

    The ``.py`` repeatable and undo rows are the point of this test. A
    repeatable Python script is typed ``REPEATABLE`` and an undo Python script
    ``UNDO_SQL``; neither records anywhere in ``type`` that the script is not
    SQL. Format is therefore **already** unrecoverable from ``type`` for every
    non-versioned role, which is why the ``PYTHON`` member carries no
    information the ``format`` attribute does not already carry — and why a
    later phase must not treat ``PYTHON`` as tidy-away-able: it is still the
    value on disk in existing history tables.
    """
    migration = Migration(script_path=_write(tmp_path, filename))
    assert migration.type is expected


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("V1__x.sql", MigrationType.SQL),
        ("V1__x.py", MigrationType.SQL),
        ("R__x.py", MigrationType.REPEATABLE),
        ("U1__x.py", MigrationType.UNDO_SQL),
    ],
)
def test_name_constructed_migration_type_is_not_format_overridden(
    filename: str, expected: MigrationType
) -> None:
    """A name-constructed ``Migration`` keeps the role type — the ``PYTHON`` override never fires.

    ``Migration.__init__`` applies the ``SQL``-to-``PYTHON`` rewrite only on the
    ``script_path`` branch. On the ``script_name`` branch — the one used for
    migrations materialised from a history row or from in-memory content — a
    versioned ``.py`` script stays ``MigrationType.SQL`` even though ``format``
    is correctly detected as Python.

    So ``type`` for the same logical migration depends on *how the object was
    built*, not on what the migration is. That asymmetry is exactly the
    role/format conflation, and it is pinned here so a later phase cannot
    "unify" the two branches without noticing that it changes which string gets
    persisted.
    """
    migration = Migration(script_name=filename, content="-- noop\n")
    assert migration.type is expected


# ---------------------------------------------------------------------------
# 2. What actually reaches storage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, expected_type_string",
    [
        ("V1__x.py", "PYTHON"),
        ("V1__x.sql", "SQL"),
        ("R__x.py", "REPEATABLE"),
        ("U1__x.py", "UNDO_SQL"),
    ],
)
def test_recorded_migration_info_carries_enum_member_name(
    tmp_path: Path, filename: str, expected_type_string: str
) -> None:
    """The dict handed to ``provider.record_migration`` carries the enum *member name*.

    Asserted against the real write path in
    ``core/migration/history/migration_history_manager.py`` rather than against
    the enum, so the test covers the string that is genuinely persisted — the
    manager could stop using ``.name``, or stop including ``type`` at all, and
    an enum-level assertion would not notice.
    """
    provider = RecordingProvider()
    manager = MigrationHistoryManager(provider=provider, schema="public", installed_by="tester")
    migration = Migration(script_path=_write(tmp_path, filename))

    manager.record_migration(migration, success=True, execution_time=1)

    assert len(provider.recorded) == 1
    _schema, migration_info, _table = provider.recorded[0]
    assert migration_info["type"] == expected_type_string


# ---------------------------------------------------------------------------
# 3. Round-trip through the history row
# ---------------------------------------------------------------------------


def test_vocabulary_is_exactly_these_names() -> None:
    """Pin the full member roster against a literal list, not a derived one.

    Unlike a ``list(MigrationType)``-derived parametrization, this comparison
    has one side that does not move when the enum changes: renaming a member,
    adding one, or deleting one all show up here as a list mismatch, which is
    exactly the drift ``test_every_member_name_round_trips_from_history_row``
    below cannot see because both of its sides are derived from the same enum.
    """
    assert [member.name for member in MigrationType] == list(PERSISTED_TYPE_NAMES)


@pytest.mark.parametrize("stored", PERSISTED_TYPE_NAMES)
def test_stored_name_round_trips_from_literal_roster(stored: str) -> None:
    """Every name in the literal roster still reads back as the matching member.

    Parametrized over ``PERSISTED_TYPE_NAMES`` rather than ``list(MigrationType)``
    so that removing a member shrinks the enum but not this parametrization: the
    missing name is still looked up here and fails loudly (``KeyError`` /
    assertion failure) instead of the test file quietly reporting fewer cases.
    """
    applied = AppliedMigration.from_history_row({"type": stored, "script": "V1__x.sql"})
    assert applied.type.name == stored


@pytest.mark.parametrize("member", list(MigrationType), ids=lambda m: m.name)
def test_every_member_name_round_trips_from_history_row(member: MigrationType) -> None:
    """Every persisted member name reads back as the same member.

    This is the invariant the whole file exists for: history rows are matched by
    ``MigrationType[type_str]``, so a renamed or removed member turns existing
    rows into ``UNKNOWN``.

    Kept alongside ``test_stored_name_round_trips_from_literal_roster`` above:
    this parametrization is derived from the enum under test
    (``list(MigrationType)``), so it is a tautology on its own — rename a member
    and the parametrization renames with it, delete one and it shrinks. It still
    round-trips whatever members exist *today*, which is useful, but the literal
    roster is what actually locks the vocabulary against drift.
    """
    applied = AppliedMigration.from_history_row({"type": member.name, "script": "V1__x.sql"})
    assert applied.type is member


def test_python_history_row_round_trips() -> None:
    """The concrete pairing this program must not break: ``"PYTHON"`` in, ``PYTHON`` out."""
    applied = AppliedMigration.from_history_row({"type": "PYTHON", "script": "V1__x.py"})
    assert applied.type is MigrationType.PYTHON


@pytest.mark.parametrize("member", list(MigrationType), ids=lambda m: m.name)
def test_member_name_and_value_are_identical(member: MigrationType) -> None:
    """Every member's ``.value`` equals its ``.name`` — an accident the codebase relies on.

    The write path persists ``migration.type.name`` and the read path looks the
    stored string up in ``MigrationType.__members__``, so *names* are the wire
    format and values are, in principle, free. They are not free in practice:
    ``VERSIONED_SCRIPT_TYPES`` in ``core/migration/migration.py`` is built from
    ``MigrationType.SQL.value`` / ``MigrationType.PYTHON.value`` while
    ``core/migration/_type_match.py`` tests membership using the migration
    type's *name*. That comparison only succeeds because the two coincide.

    Consequently a ``.name``/``.value`` mix-up is currently invisible: swapping
    one for the other anywhere changes nothing. Pinning the identity keeps it
    that way, so that giving a member a value distinct from its name — which
    would silently drop it out of ``VERSIONED_SCRIPT_TYPES`` and stop its
    migrations counting as versioned — fails here first.
    """
    assert member.value == member.name


@pytest.mark.parametrize("stored_value", ["VERSIONED", "sql", "python", "", "SQL_SCRIPT"])
def test_unrecognised_history_type_degrades_to_unknown(stored_value: str) -> None:
    """An unrecognised stored value degrades to ``UNKNOWN`` — silently, and by design today.

    Pinned as *known* behaviour so that changing it (to raise, to warn, or to
    map through a compatibility table) is a deliberate decision rather than an
    accident. Note the lookup is case-sensitive: a lowercased ``"sql"`` does not
    match, it becomes ``UNKNOWN`` like any other stranger.
    """
    applied = AppliedMigration.from_history_row({"type": stored_value, "script": "V1__x.sql"})
    assert applied.type is MigrationType.UNKNOWN


def test_leading_whitespace_is_not_tolerated() -> None:
    """``" SQL"`` (leading space) degrades to ``UNKNOWN``, not ``MigrationType.SQL``.

    ``from_history_row`` does no ``.strip()`` today. A ``CHAR``-padding storage
    engine or a CSV-import path could plausibly introduce padding, so this pins
    that padding must NOT be silently tolerated — a later change that adds
    ``.strip()`` to make padded values round-trip has to touch this test on
    purpose, not slip in as an unrelated tidy-up.
    """
    applied = AppliedMigration.from_history_row({"type": " SQL", "script": "V1__x.sql"})
    assert applied.type is MigrationType.UNKNOWN


# ---------------------------------------------------------------------------
# 4. Column-width invariant
# ---------------------------------------------------------------------------


def test_member_names_fit_the_history_type_column() -> None:
    """No member name may exceed 20 characters — the width of the persisted column.

    The history table declares ``type`` as a 20-character string on ten of the
    thirteen storage shapes (SQLite, DuckDB and CosmosDB are the unbounded
    exceptions); see for example
    ``db/plugins/postgresql/postgresql/history_manager.py`` (``type VARCHAR(20)
    NOT NULL``), ``db/plugins/mysql/mysql/history_manager.py`` (same),
    ``db/plugins/sqlserver/sqlserver/history_manager.py``
    (``type NVARCHAR(20)``) and ``db/plugins/oracle/oracle/history_manager.py``
    (``TYPE VARCHAR2(20)``).

    Nothing in the codebase enforces this today: a longer, more honest member
    name — ``VERSIONED_PYTHON``, say — would pass every other test and then fail
    at INSERT time against a real database, on those engines only, and only once
    a migration of that type was actually run.
    """
    too_long = [member.name for member in MigrationType if len(member.name) > 20]
    assert not too_long, f"member names exceed the VARCHAR(20) history column: {too_long}"


# ---------------------------------------------------------------------------
# 5. Meaning, not just spelling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member, versioned",
    [
        (MigrationType.SQL, True),
        (MigrationType.PYTHON, True),
        (MigrationType.REPEATABLE, False),
        (MigrationType.UNDO_SQL, False),
        (MigrationType.BASELINE, False),
        (MigrationType.CALLBACK, False),
        (MigrationType.DELETE, False),
        (MigrationType.UNKNOWN, False),
    ],
    ids=lambda p: p.name if isinstance(p, MigrationType) else str(p),
)
def test_versioned_semantics_are_frozen(member: MigrationType, versioned: bool) -> None:
    """``is_versioned`` classifies every member as pinned here, not merely spelled correctly.

    The tests above pin the *name* that gets persisted and pin the *enum* out
    against renames/deletions, but nothing previously asserted what a member
    *means*. A plausible-looking "tidy-up" like rebuilding
    ``VERSIONED_SCRIPT_TYPES`` from ``{MigrationType.SQL.value}`` (dropping
    ``PYTHON``) would pass every test above — the name ``"PYTHON"`` still
    round-trips fine — while silently making ``migrate`` stop counting Python
    migrations as versioned. This test fails that change directly.
    """
    assert is_versioned(member) is versioned
