"""Test utility functions for cleaning test environment."""

import os
import shutil
from pathlib import Path


def should_clean_test_environment(node_path: object, project_root: Path) -> bool:
    """Return whether the global filesystem cleanup should run for this test node."""
    if node_path is None:
        return True

    try:
        Path(node_path).resolve().relative_to(project_root / "tests" / "unit")
    except (TypeError, ValueError, OSError):
        return True
    return False


def ensure_clean_test_environment(test_name: str) -> None:
    """Ensure clean test environment by removing logs and temp files.

    Args:
        test_name: Name of the test for targeted cleanup
    """
    # Clean up log files
    log_dir = Path("./logs")
    if log_dir.exists():
        try:
            # Remove log files related to this test
            for log_file in log_dir.glob(f"*{test_name}*"):
                try:
                    log_file.unlink()
                except Exception:
                    pass  # Ignore errors when deleting log files
        except Exception:
            pass  # Ignore errors during cleanup

    # Clean up temporary files in common temp locations
    temp_dirs = [
        Path("/tmp"),
        Path(os.environ.get("TMPDIR", "/tmp")),
        Path("./tmp"),
        Path("./temp"),
    ]

    for temp_dir in temp_dirs:
        if temp_dir.exists():
            try:
                # Remove temp files related to this test
                for temp_file in temp_dir.glob(f"*{test_name}*"):
                    try:
                        if temp_file.is_file():
                            temp_file.unlink()
                        elif temp_file.is_dir():
                            shutil.rmtree(temp_file, ignore_errors=True)
                    except Exception:
                        pass  # Ignore errors when deleting temp files
            except Exception:
                pass  # Ignore errors during cleanup

    # Clean up any .pyc files in __pycache__ directories
    for pycache_dir in Path(".").rglob("__pycache__"):
        try:
            # Only clean if it's in a test-related directory
            if "test" in str(pycache_dir).lower():
                for pyc_file in pycache_dir.glob(f"*{test_name}*"):
                    try:
                        pyc_file.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
