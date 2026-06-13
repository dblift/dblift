"""Tests for SequenceDiff, ExtensionDiff, and EventDiff severity refinement (story 16-16).

Validates NEW-BUG-05 fix: differentiated severity levels based on change impact.
"""

import pytest

from core.comparison.diff_models import DiffSeverity, EventDiff, ExtensionDiff, SequenceDiff


@pytest.mark.unit
class TestSequenceDiffSeverity1616:
    """AC#1, AC#2, AC#3 — SequenceDiff min/max_value_changed → ERROR."""

    def test_min_value_changed_is_error(self):
        diff = SequenceDiff(object_name="seq", min_value_changed=(1, 100))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "min_value_changed must be ERROR"

    def test_max_value_changed_is_error(self):
        diff = SequenceDiff(object_name="seq", max_value_changed=(9999999, 999))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "max_value_changed must be ERROR"

    def test_min_and_max_changed_is_error(self):
        diff = SequenceDiff(
            object_name="seq",
            min_value_changed=(1, 100),
            max_value_changed=(9999, 100),
        )
        assert diff.severity == DiffSeverity.ERROR

    def test_error_takes_precedence_over_owned_by(self):
        """min_value_changed + owned_by_changed → ERROR (pas WARNING)."""
        diff = SequenceDiff(
            object_name="seq",
            min_value_changed=(1, 100),
            owned_by_changed=(("t", "id"), ("t2", "id")),
        )
        assert diff.severity == DiffSeverity.ERROR

    def test_max_value_changed_and_owned_by_changed_is_error(self):
        """max_value_changed + owned_by_changed → ERROR (pas WARNING)."""
        diff = SequenceDiff(
            object_name="seq",
            max_value_changed=(9999999, 100),
            owned_by_changed=(("t", "id"), ("t2", "id")),
        )
        assert diff.severity == DiffSeverity.ERROR

    def test_cycle_changed_is_info(self):
        diff = SequenceDiff(object_name="seq", cycle_changed=(True, False))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO, "cycle_changed must be INFO"

    def test_temp_changed_is_info(self):
        diff = SequenceDiff(object_name="seq", temp_changed=(True, False))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO, "temp_changed must be INFO"


@pytest.mark.unit
class TestExtensionDiffSeverity:
    """AC#4, AC#5 — ExtensionDiff schema_changed → ERROR."""

    def test_schema_changed_is_error(self):
        diff = ExtensionDiff(object_name="pg_stat", schema_changed=("public", "ext"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "schema_changed must be ERROR"

    def test_version_changed_only_is_warning(self):
        diff = ExtensionDiff(object_name="pg_stat", version_changed=("1.0", "1.1"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "version_changed alone must be WARNING"

    def test_schema_and_version_changed_is_error(self):
        """ERROR prime même si version_changed est aussi présent."""
        diff = ExtensionDiff(
            object_name="pg_stat",
            schema_changed=("public", "ext"),
            version_changed=("1.0", "1.1"),
        )
        assert diff.severity == DiffSeverity.ERROR


@pytest.mark.unit
class TestEventDiffSeverity:
    """AC#6, AC#7, AC#8 — EventDiff hiérarchie WARNING/INFO."""

    def test_schedule_changed_is_warning(self):
        diff = EventDiff(object_name="ev", schedule_changed=("EVERY 1 HOUR", "EVERY 2 HOUR"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "schedule_changed must be WARNING"

    def test_enabled_changed_only_is_info(self):
        diff = EventDiff(object_name="ev", enabled_changed=(True, False))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO, "enabled_changed alone must be INFO"

    def test_definition_changed_is_warning(self):
        diff = EventDiff(object_name="ev", definition_changed=True)
        assert diff.severity == DiffSeverity.WARNING

    def test_event_type_changed_is_warning(self):
        diff = EventDiff(object_name="ev", event_type_changed=("ONE TIME", "RECURRING"))
        assert diff.severity == DiffSeverity.WARNING

    def test_definer_changed_only_is_info(self):
        diff = EventDiff(object_name="ev", definer_changed=("user1@host", "user2@host"))
        assert diff.severity == DiffSeverity.INFO

    def test_comment_changed_only_is_info(self):
        diff = EventDiff(object_name="ev", comment_changed=("old", "new"))
        assert diff.severity == DiffSeverity.INFO

    def test_warning_takes_precedence_over_info(self):
        """schedule_changed + enabled_changed → WARNING (pas INFO)."""
        diff = EventDiff(
            object_name="ev",
            schedule_changed=("EVERY 1 HOUR", "EVERY 2 HOUR"),
            enabled_changed=(True, False),
        )
        assert diff.severity == DiffSeverity.WARNING
