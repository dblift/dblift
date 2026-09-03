"""Story 23-7: Structural tests verifying removal of try:pass dead code artifacts (DEAD-NEW-04/05)."""

import inspect

import pytest

pytestmark = [pytest.mark.unit]


def test_log_py_jinja_available_no_try_except():
    """DEAD-NEW-04: log.py JINJA_AVAILABLE no longer wrapped in dead try/except."""
    import dblift.core.logger.log as mod

    src = inspect.getsource(mod)
    # The try:pass artifact is gone — JINJA_AVAILABLE should be a direct assignment
    assert "JINJA_AVAILABLE = True" in src
    # No dead try/except wrapping a bare pass before JINJA_AVAILABLE
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "JINJA_AVAILABLE = True" in line:
            # The preceding non-blank line should NOT be 'pass'
            preceding = [l.strip() for l in lines[:i] if l.strip()]
            assert preceding[-1] != "pass", "pass found immediately before JINJA_AVAILABLE = True"
            break


def test_log_py_jinja_available_is_true():
    """DEAD-NEW-04: JINJA_AVAILABLE is True at runtime."""
    from dblift.core.logger.log import JINJA_AVAILABLE

    assert JINJA_AVAILABLE is True


def test_repair_command_execute_no_pass_in_try():
    """DEAD-NEW-04: repair_command execute() MISSING_SCRIPT try block no longer starts with bare pass."""
    from dblift.core.migration.commands.repair_command import RepairCommand

    src = inspect.getsource(RepairCommand.execute)
    lines = [l.strip() for l in src.splitlines() if l.strip()]
    # Verify no 'try:' block immediately followed by 'pass' then a comment
    for i, line in enumerate(lines):
        if line == "try:" and i + 1 < len(lines):
            next_non_blank = lines[i + 1]
            assert (
                next_non_blank != "pass"
            ), f"Dead 'pass' still present after try: at position {i} in RepairCommand.execute"


def test_get_index_syntax_removed():
    """DEAD-NEW-05: get_index_syntax nested function removed (Epic 26 — logic moved to quirks).

    The ``_generate_basic_create_statement`` method has been relocated to the
    dialect generators (P4 refactor), so we verify the dead helper is absent
    from the generator instead.
    """
    import dblift.core.sql_model.index as index_module

    src = inspect.getsource(index_module)
    assert (
        "get_index_syntax" not in src
    ), "get_index_syntax should be fully removed (replaced by quirks)"
