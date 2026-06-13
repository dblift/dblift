"""Per-module tests for ``core.comparison._diff_simple``.

PR-G9: narrow coverage on the extracted module (PR-G4 split). Each ``*Diff``
in this module uses the homogeneous "field-set ⇒ fixed severity" pattern
via ``DiffResult._set_severity_from_pairs``.
"""

import pytest

from core.comparison._diff_base import DiffSeverity
from core.comparison._diff_simple import (
    DatabaseLinkDiff,
    EventDiff,
    ExtensionDiff,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    LinkedServerDiff,
    ModuleDiff,
    PackageDiff,
    SequenceDiff,
    SynonymDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# SequenceDiff
# ---------------------------------------------------------------------------


class TestSequenceDiff:
    def test_no_diffs(self):
        d = SequenceDiff(object_name="s", sequence_name="s")
        assert d.has_diffs is False
        assert d.object_type == "sequence"

    def test_min_value_changed_is_error(self):
        d = SequenceDiff(object_name="s", sequence_name="s", min_value_changed=(1, 5))
        assert d.severity == DiffSeverity.ERROR

    def test_max_value_changed_is_error(self):
        d = SequenceDiff(object_name="s", sequence_name="s", max_value_changed=(100, 50))
        assert d.severity == DiffSeverity.ERROR

    def test_start_value_changed_is_info(self):
        d = SequenceDiff(object_name="s", sequence_name="s", start_value_changed=(1, 2))
        assert d.severity == DiffSeverity.INFO
        assert d.has_diffs is True

    def test_owned_by_changed_is_warning(self):
        d = SequenceDiff(
            object_name="s",
            sequence_name="s",
            owned_by_changed=(("t", "c"), ("t", "d")),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_error_overrides_warning(self):
        d = SequenceDiff(
            object_name="s",
            sequence_name="s",
            min_value_changed=(1, 5),
            owned_by_changed=(("t", "c"), ("t", "d")),
        )
        assert d.severity == DiffSeverity.ERROR


# ---------------------------------------------------------------------------
# TriggerDiff
# ---------------------------------------------------------------------------


class TestTriggerDiff:
    def test_no_diffs(self):
        d = TriggerDiff(object_name="trg", trigger_name="trg", table_name="t")
        assert d.has_diffs is False
        assert d.object_type == "trigger"

    def test_timing_changed_is_error(self):
        d = TriggerDiff(
            object_name="trg",
            trigger_name="trg",
            table_name="t",
            timing_changed=("BEFORE", "AFTER"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_function_changed_is_error(self):
        d = TriggerDiff(
            object_name="trg",
            trigger_name="trg",
            table_name="t",
            function_changed=("old_fn", "new_fn"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_definition_changed_is_warning(self):
        d = TriggerDiff(
            object_name="trg",
            trigger_name="trg",
            table_name="t",
            definition_changed=True,
        )
        assert d.severity == DiffSeverity.WARNING

    def test_when_clause_changed_is_warning(self):
        d = TriggerDiff(
            object_name="trg",
            trigger_name="trg",
            table_name="t",
            when_clause_changed=("OLD = 0", "OLD = 1"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_to_dict_includes_all_fields(self):
        # Cover the to_dict serialization (lines 124-143).
        d = TriggerDiff(
            object_name="trg",
            trigger_name="trg",
            table_name="t",
            timing_changed=("BEFORE", "AFTER"),
            event_changed=("INSERT", "UPDATE"),
            constraint_trigger_changed=(False, True),
            definer_changed=("a@h", "b@h"),
            definition_changed=True,
            enabled_changed=(True, False),
            function_changed=("f1", "f2"),
            function_schema_changed=("s1", "s2"),
            function_arguments_changed=([], ["x"]),
            when_clause_changed=("OLD.x = 1", "OLD.x = 2"),
            constraint_deferrable_changed=(False, True),
            constraint_initially_deferred_changed=(False, True),
        )
        out = d.to_dict()
        for key in (
            "trigger_name",
            "table_name",
            "timing_changed",
            "event_changed",
            "constraint_trigger_changed",
            "definer_changed",
            "definition_changed",
            "enabled_changed",
            "function_changed",
            "function_schema_changed",
            "function_arguments_changed",
            "when_clause_changed",
            "constraint_deferrable_changed",
            "constraint_initially_deferred_changed",
        ):
            assert key in out
        assert out["trigger_name"] == "trg"
        assert out["definition_changed"] is True

    def test_to_dict_no_diffs_still_serializes(self):
        d = TriggerDiff(object_name="trg", trigger_name="trg", table_name="t")
        out = d.to_dict()
        assert out["timing_changed"] is None
        assert out["definition_changed"] is False


# ---------------------------------------------------------------------------
# SynonymDiff
# ---------------------------------------------------------------------------


class TestSynonymDiff:
    def test_target_changed_is_error(self):
        d = SynonymDiff(
            object_name="syn",
            synonym_name="syn",
            target_changed=("old_t", "new_t"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_target_schema_changed_is_error(self):
        d = SynonymDiff(
            object_name="syn",
            synonym_name="syn",
            target_schema_changed=("s1", "s2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_target_database_changed_is_warning(self):
        d = SynonymDiff(
            object_name="syn",
            synonym_name="syn",
            target_database_changed=("d1", "d2"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_db_link_changed_is_warning(self):
        d = SynonymDiff(
            object_name="syn",
            synonym_name="syn",
            db_link_changed=("link_a", "link_b"),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# PackageDiff
# ---------------------------------------------------------------------------


class TestPackageDiff:
    def test_spec_changed_is_error(self):
        d = PackageDiff(object_name="pkg", package_name="pkg", spec_changed=True)
        assert d.severity == DiffSeverity.ERROR

    def test_body_changed_is_warning(self):
        d = PackageDiff(object_name="pkg", package_name="pkg", body_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_no_diffs(self):
        d = PackageDiff(object_name="pkg", package_name="pkg")
        assert d.has_diffs is False


# ---------------------------------------------------------------------------
# DatabaseLinkDiff
# ---------------------------------------------------------------------------


class TestDatabaseLinkDiff:
    def test_host_changed_is_error(self):
        d = DatabaseLinkDiff(
            object_name="dl",
            link_name="dl",
            host_changed=("h1", "h2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_username_changed_is_error(self):
        d = DatabaseLinkDiff(
            object_name="dl",
            link_name="dl",
            username_changed=("u1", "u2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_public_changed_is_warning(self):
        d = DatabaseLinkDiff(
            object_name="dl",
            link_name="dl",
            public_changed=(False, True),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# LinkedServerDiff
# ---------------------------------------------------------------------------


class TestLinkedServerDiff:
    def test_product_changed_is_error(self):
        d = LinkedServerDiff(
            object_name="ls",
            server_name="ls",
            product_changed=("SQL", "Oracle"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_provider_changed_is_error(self):
        d = LinkedServerDiff(
            object_name="ls",
            server_name="ls",
            provider_changed=("p1", "p2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_data_source_changed_is_error(self):
        d = LinkedServerDiff(
            object_name="ls",
            server_name="ls",
            data_source_changed=("d1", "d2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_username_changed_is_error(self):
        d = LinkedServerDiff(
            object_name="ls",
            server_name="ls",
            username_changed=("u1", "u2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_catalog_changed_is_warning(self):
        d = LinkedServerDiff(
            object_name="ls",
            server_name="ls",
            catalog_changed=("c1", "c2"),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# ModuleDiff
# ---------------------------------------------------------------------------


class TestModuleDiff:
    def test_no_diffs(self):
        d = ModuleDiff(object_name="m", module_name="m")
        assert d.has_diffs is False

    def test_definition_changed_is_warning(self):
        d = ModuleDiff(object_name="m", module_name="m", definition_changed=True)
        assert d.has_diffs is True
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# ForeignDataWrapperDiff
# ---------------------------------------------------------------------------


class TestForeignDataWrapperDiff:
    def test_handler_changed_is_error(self):
        d = ForeignDataWrapperDiff(
            object_name="fdw",
            fdw_name="fdw",
            handler_changed=("h1", "h2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_validator_changed_is_error(self):
        d = ForeignDataWrapperDiff(
            object_name="fdw",
            fdw_name="fdw",
            validator_changed=("v1", "v2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_options_changed_is_warning(self):
        d = ForeignDataWrapperDiff(
            object_name="fdw",
            fdw_name="fdw",
            options_changed=({}, {"opt": "val"}),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# ForeignServerDiff
# ---------------------------------------------------------------------------


class TestForeignServerDiff:
    def test_fdw_changed_is_error(self):
        d = ForeignServerDiff(
            object_name="fs",
            server_name="fs",
            fdw_changed=("a", "b"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_host_changed_is_error(self):
        d = ForeignServerDiff(
            object_name="fs",
            server_name="fs",
            host_changed=("h1", "h2"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_port_changed_is_error(self):
        d = ForeignServerDiff(
            object_name="fs",
            server_name="fs",
            port_changed=(5432, 5433),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_dbname_changed_is_warning(self):
        d = ForeignServerDiff(
            object_name="fs",
            server_name="fs",
            dbname_changed=("a", "b"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_options_changed_is_warning(self):
        d = ForeignServerDiff(
            object_name="fs",
            server_name="fs",
            options_changed=({}, {"a": "b"}),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# ExtensionDiff
# ---------------------------------------------------------------------------


class TestExtensionDiff:
    def test_schema_changed_is_error(self):
        d = ExtensionDiff(
            object_name="ext",
            extension_name="ext",
            schema_changed=("public", "audit"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_version_changed_is_warning(self):
        d = ExtensionDiff(
            object_name="ext",
            extension_name="ext",
            version_changed=("1.0", "2.0"),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# EventDiff
# ---------------------------------------------------------------------------


class TestEventDiff:
    def test_definition_changed_is_warning(self):
        d = EventDiff(object_name="evt", event_name="evt", definition_changed=True)
        assert d.severity == DiffSeverity.WARNING

    def test_event_type_changed_is_warning(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            event_type_changed=("ONE TIME", "RECURRING"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_schedule_changed_is_warning(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            schedule_changed=("daily", "weekly"),
        )
        assert d.severity == DiffSeverity.WARNING

    def test_enabled_changed_is_info(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            enabled_changed=(True, False),
        )
        assert d.severity == DiffSeverity.INFO

    def test_definer_changed_is_info(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            definer_changed=("a@h", "b@h"),
        )
        assert d.severity == DiffSeverity.INFO

    def test_comment_changed_is_info(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            comment_changed=("c1", "c2"),
        )
        assert d.severity == DiffSeverity.INFO

    def test_warning_dominates_info(self):
        d = EventDiff(
            object_name="evt",
            event_name="evt",
            schedule_changed=("a", "b"),
            enabled_changed=(True, False),
        )
        assert d.severity == DiffSeverity.WARNING


# ---------------------------------------------------------------------------
# UserDefinedTypeDiff
# ---------------------------------------------------------------------------


class TestUserDefinedTypeDiff:
    def test_type_category_changed_is_error(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            type_category_changed=("ENUM", "COMPOSITE"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_base_type_changed_is_error(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            base_type_changed=("INTEGER", "BIGINT"),
        )
        assert d.severity == DiffSeverity.ERROR

    def test_attributes_changed_is_warning(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            attributes_changed=True,
        )
        assert d.severity == DiffSeverity.WARNING

    def test_enum_values_changed_is_warning(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            enum_values_changed=True,
        )
        assert d.severity == DiffSeverity.WARNING

    def test_definition_changed_is_warning(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            definition_changed=True,
        )
        assert d.severity == DiffSeverity.WARNING

    def test_error_dominates_warning(self):
        d = UserDefinedTypeDiff(
            object_name="udt",
            type_name="udt",
            type_category_changed=("ENUM", "COMPOSITE"),
            attributes_changed=True,
        )
        assert d.severity == DiffSeverity.ERROR
