"""Structural tests verifying removal of try:pass dead code artifacts."""

import inspect

import pytest

pytestmark = [pytest.mark.unit]


def test_log_py_jinja_availability_is_discovered_on_access(monkeypatch):
    """The historical availability flag resolves without probing during import."""
    import dblift.core.logger.log as mod

    calls = []

    def unavailable(name):
        calls.append(name)
        return False

    monkeypatch.setattr(mod, "module_available", unavailable)
    assert "JINJA_AVAILABLE" not in vars(mod)
    assert calls == []
    assert mod.JINJA_AVAILABLE is False
    assert calls == ["jinja2"]


def test_log_py_jinja_available_is_true():
    """JINJA_AVAILABLE is True where Jinja2 is installed (the test environment)."""
    from dblift.core.logger.log import JINJA_AVAILABLE

    assert JINJA_AVAILABLE is True


def test_repair_command_execute_no_pass_in_try():
    """repair_command execute() MISSING_SCRIPT try block no longer starts with bare pass."""
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
    """get_index_syntax nested function removed (logic moved to quirks).

    Verify the dead helper remains absent from the index model.
    """
    import dblift.core.sql_model.index as index_module

    src = inspect.getsource(index_module)
    assert (
        "get_index_syntax" not in src
    ), "get_index_syntax should be fully removed (replaced by quirks)"
