"""Migrations written as one group must be undone or kept applied together.

A group is marked purely by filename tag (``strip_migration_tags``): every
migration carrying the same ``GROUP_TAG_PREFIX``-prefixed tag is one unit.
Plain ``dblift undo`` (no ``--target-version``) widens its usual "undo just
the most recently applied migration" plan to the whole group; ``undo
--target-version`` does the same when the target lands inside a group. A
version sharing another migration's *version-number shape* (e.g. ``V9_1``
next to ``V9_2``) but no tag must never be swept in -- grouping is opt-in via
the tag, never inferred from naming.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.undo_command import UndoCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.rules.migration_rules import (
    GROUP_TAG_PREFIX,
    MigrationRules,
    expand_undo_set_to_groups,
    group_tag_of,
)
from dblift.core.migration.state.migration_state_manager import MigrationStateManager


def _make_migration(version, tags=(), mtype=MigrationType.SQL, success=True):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.tags = list(tags)
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_command(applied_migrations, undo_scripts=None):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    migration_state.all_applied_objects = list(applied_migrations)
    migration_state.pending_objects = [s for s in (undo_scripts or [])]
    migration_state.pending = [
        MagicMock(status="Available", version=str(s.version)) for s in (undo_scripts or [])
    ]
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None
    _filter_mgr = MigrationStateManager.__new__(MigrationStateManager)
    state_manager.apply_filters_to_migrations.side_effect = (
        lambda migrations, **kwargs: _filter_mgr.apply_filters_to_migrations(migrations, **kwargs)
    )

    execution_engine = MagicMock()
    execution_engine.executor_factory = MagicMock(get_executor=MagicMock(return_value=None))

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=MagicMock(get_migration_scripts=MagicMock(return_value=[])),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=execution_engine,
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=MigrationRules(MagicMock()),
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)
    if undo_scripts:
        cmd._find_undo_script = MagicMock(
            side_effect=lambda migration, state: next(
                (s for s in undo_scripts if str(s.version) == str(migration.version)), None
            )
        )
    else:
        cmd._find_undo_script = MagicMock(return_value=MagicMock())
    return cmd


@pytest.mark.unit
class TestGroupTagOf:
    def test_no_tags(self):
        assert group_tag_of(_make_migration(1, tags=[])) is None

    def test_ordinary_user_tag_is_not_a_group_tag(self):
        assert group_tag_of(_make_migration(1, tags=["prod"])) is None

    def test_group_tag_recognized(self):
        tag = f"{GROUP_TAG_PREFIX}V9"
        assert group_tag_of(_make_migration(1, tags=["prod", tag])) == tag

    def test_group_tag_prefix_is_filename_safe(self):
        # The tag lives inside a migration *filename* ("V9_1__x[<tag>].sql");
        # any of <>:"/\|?* there is illegal on Windows (a colon doubly so --
        # it's also the drive-letter separator), so a script carrying an
        # unsafe tag could not even be checked out there.
        illegal = set('<>:"/\\|?*')
        assert not (set(GROUP_TAG_PREFIX) & illegal)


@pytest.mark.unit
class TestExpandUndoSetToGroups:
    def test_no_group_tag_returns_seed_unchanged(self):
        rules = MigrationRules(MagicMock())
        v1 = _make_migration(1)
        full_set, added = expand_undo_set_to_groups(rules, [v1], [v1], [v1], version_ranks={})
        assert full_set == [v1]
        assert added == []

    def test_pulls_in_other_applied_members_of_the_same_group(self):
        rules = MigrationRules(MagicMock())
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        v9_3 = _make_migration("9_3", tags=[tag])
        pool = [v9_1, v9_2, v9_3]

        full_set, added = expand_undo_set_to_groups(rules, [v9_3], pool, pool, version_ranks={})

        assert [m.version for m in full_set] == ["9_3", "9_2", "9_1"]
        assert added == [v9_1, v9_2] or added == [v9_2, v9_1]

    def test_ignores_pool_members_with_a_different_group_tag(self):
        rules = MigrationRules(MagicMock())
        tag_a = f"{GROUP_TAG_PREFIX}V9"
        tag_b = f"{GROUP_TAG_PREFIX}V10"
        v9_1 = _make_migration("9_1", tags=[tag_a])
        v10_1 = _make_migration("10_1", tags=[tag_b])
        pool = [v9_1, v10_1]

        full_set, added = expand_undo_set_to_groups(rules, [v9_1], pool, pool, version_ranks={})

        assert full_set == [v9_1]
        assert added == []

    def test_skips_pool_members_already_undone(self):
        rules = MigrationRules(MagicMock())
        rules._is_currently_undone = MagicMock(
            side_effect=lambda version, *a, **k: version == "9_1"
        )
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        pool = [v9_1, v9_2]

        full_set, added = expand_undo_set_to_groups(rules, [v9_2], pool, pool, version_ranks={})

        assert full_set == [v9_2]
        assert added == []


@pytest.mark.unit
class TestPlainUndoRevertsWholeGroup:
    def test_undoes_every_applied_member_highest_first(self):
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        v9_3 = _make_migration("9_3", tags=[tag])
        cmd = _make_command([v9_1, v9_2, v9_3])

        result = cmd.execute(scripts_dir=MagicMock())

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == ["9_3", "9_2", "9_1"]
        assert result.success

    def test_untagged_version_shaped_migration_is_not_swept_into_a_group(self):
        # V9_1 / V9_2 look like generated parts but carry no group tag: an
        # independently authored migration must never be grouped by naming
        # shape alone.
        v9_1 = _make_migration("9_1", tags=[])
        v9_2 = _make_migration("9_2", tags=[])
        cmd = _make_command([v9_1, v9_2])

        cmd.execute(scripts_dir=MagicMock())

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == ["9_2"]

    def test_no_group_tag_undoes_only_the_most_recent(self):
        v1 = _make_migration(1)
        v2 = _make_migration(2)
        cmd = _make_command([v1, v2])

        cmd.execute(scripts_dir=MagicMock())

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == [2]


@pytest.mark.unit
class TestTargetVersionInsideGroupWidensScope:
    def test_target_version_below_group_undoes_whole_group(self):
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        v9_3 = _make_migration("9_3", tags=[tag])
        cmd = _make_command([v9_1, v9_2, v9_3])

        result = cmd.execute(scripts_dir=MagicMock(), target_version="8")

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == ["9_3", "9_2", "9_1"]
        assert result.success

    def test_target_version_landing_mid_group_still_undoes_the_whole_group(self):
        # --target-version 9_2 would normally undo only 9_3 (strictly above
        # the target); 9_2 (the target itself, still applied) and 9_1 share
        # 9_3's group tag, so the whole group is undone rather than leaving
        # part of it applied.
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        v9_3 = _make_migration("9_3", tags=[tag])
        cmd = _make_command([v9_1, v9_2, v9_3])

        result = cmd.execute(scripts_dir=MagicMock(), target_version="9_2")

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == ["9_3", "9_2", "9_1"]
        assert result.success

    def test_target_version_outside_group_leaves_group_untouched(self):
        tag = f"{GROUP_TAG_PREFIX}V9"
        v9_1 = _make_migration("9_1", tags=[tag])
        v9_2 = _make_migration("9_2", tags=[tag])
        cmd = _make_command([v9_1, v9_2])

        result = cmd.execute(scripts_dir=MagicMock(), target_version="9_2")

        undone_versions = [call.args[0].version for call in cmd._find_undo_script.call_args_list]
        assert undone_versions == []
        assert result.success
