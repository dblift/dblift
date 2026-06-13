"""Story 23-1: DEAD-NEW-01 — structural guards for dead import removal."""

import pytest

pytestmark = [pytest.mark.unit]


def test_diff_result_still_accessible_from_core_logger():
    """DiffResult must remain re-exported from core.logger (tests depend on this path)."""
    from core.logger import DiffResult

    assert DiffResult is not None


def test_comparator_does_not_expose_dead_utility_imports():
    """comparator.py should not re-export comparison_utils functions it doesn't use."""
    import core.comparison.comparator as mod

    # extract_base_identity_type and is_system_generated_constraint_name are in
    # comparison_utils; no production code or test imports them via comparator
    assert not hasattr(
        mod, "extract_base_identity_type"
    ), "extract_base_identity_type should not be re-exported from comparator"
    assert not hasattr(
        mod, "is_system_generated_constraint_name"
    ), "is_system_generated_constraint_name should not be re-exported from comparator"
    assert hasattr(mod, "ObjectComparator")  # sanity check module loaded


def test_cli_main_exposes_private_parser_helpers_as_reexports():
    """Private parser helpers imported from _parser_setup must be accessible via cli.main
    because tests import them directly from that namespace."""
    import cli.main as mod

    for name in [
        "_add_baseline_options",
        "_add_diff_and_target_options",
        "_add_validate_sql_options",
        "_setup_export_schema_options",
    ]:
        assert hasattr(mod, name), (
            f"{name} must be accessible in cli.main namespace "
            f"(tests/unit/cli/test_main_cli_decomposition.py imports it)"
        )


def test_export_schema_command_json_default_not_needed_as_reexport():
    """_json_default was removed from export_schema_command imports — verify the module
    still imports cleanly without it."""
    import core.migration.commands.export_schema_command as mod

    assert hasattr(mod, "ExportSchemaOptions")  # sanity check module loaded
