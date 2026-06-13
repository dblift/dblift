from pathlib import Path

from tests.utils.test_utils import should_clean_test_environment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_global_cleanup_skips_unit_tests() -> None:
    node_path = PROJECT_ROOT / "tests" / "unit" / "test_example.py"

    assert should_clean_test_environment(node_path, PROJECT_ROOT) is False


def test_global_cleanup_still_runs_for_non_unit_tests() -> None:
    node_path = PROJECT_ROOT / "tests" / "integration" / "test_example.py"

    assert should_clean_test_environment(node_path, PROJECT_ROOT) is True
