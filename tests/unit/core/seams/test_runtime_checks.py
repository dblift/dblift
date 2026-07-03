import pytest

from core.seams import runtime_checks


@pytest.fixture(autouse=True)
def _reset_registry():
    runtime_checks.clear_checks()
    yield
    runtime_checks.clear_checks()


def test_no_checks_registered_is_a_noop():
    runtime_checks.run_checks("migration.pre_execution")


def test_registered_check_runs_for_its_point():
    calls = []
    runtime_checks.register_check("migration.pre_execution", lambda: calls.append(1))
    runtime_checks.run_checks("migration.pre_execution")
    assert calls == [1]


def test_check_for_other_point_does_not_run():
    calls = []
    runtime_checks.register_check("migration.pre_execution", lambda: calls.append(1))
    runtime_checks.run_checks("command.pre_migrate")
    assert calls == []


def test_check_exception_propagates():
    def boom() -> None:
        raise RuntimeError("license invalid")

    runtime_checks.register_check("migration.pre_execution", boom)
    with pytest.raises(RuntimeError, match="license invalid"):
        runtime_checks.run_checks("migration.pre_execution")
