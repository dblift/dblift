"""
Root conftest.py for DBLift.
This file ensures that Python can find the project modules during tests.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest

# Add the project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Add the tests directory to the path
tests_dir = project_root / "tests"
sys.path.insert(0, str(tests_dir))

# Create a proper dblift module and add project root to sys.path
# This is necessary for the tests to find the project modules
sys.path.insert(0, str(project_root))

# Ensure we have a dblift module for imports
if "dblift" not in sys.modules:
    # Create a module spec
    spec = ModuleSpec("dblift", None)
    dblift_module = importlib.util.module_from_spec(spec)

    # Add essential attributes that may be expected
    dblift_module.__path__ = [str(project_root)]
    dblift_module.__package__ = "dblift"
    dblift_module.__file__ = str(project_root / "__init__.py")

    # Register the module
    sys.modules["dblift"] = dblift_module

    # Create module for each of the main submodules if they don't exist
    for submodule in ["cli", "config", "core", "db"]:
        full_name = f"dblift.{submodule}"
        if full_name not in sys.modules:
            submodule_spec = ModuleSpec(full_name, None)
            sub_mod = importlib.util.module_from_spec(submodule_spec)
            sub_mod.__path__ = [str(project_root / submodule)]
            sub_mod.__package__ = full_name
            sys.modules[full_name] = sub_mod
            # Also set it as an attribute of the dblift module
            setattr(dblift_module, submodule, sub_mod)

    print("Created dblift module with proper submodule structure")

# Import core modules to make them available for tests
try:
    # These imports ensure the modules are in sys.modules
    # for tests, even if not directly used in this file
    __import__("cli")
    __import__("config")
    __import__("core")
    __import__("db")

    print("Successfully imported core modules")
except ImportError as e:
    print(f"Warning: Failed to import project modules: {str(e)}")


@pytest.fixture(autouse=True)
def clean_test_environment(request):
    """
    Global autouse fixture to ensure clean test environment.

    This fixture automatically cleans up logs and temp files before and after each test
    to prevent contamination between tests.
    """
    from tests.utils.test_utils import ensure_clean_test_environment, should_clean_test_environment

    node = getattr(request, "node", None)
    node_path = getattr(node, "path", getattr(node, "fspath", None))
    if not should_clean_test_environment(node_path, project_root):
        yield
        return

    # Get test name for targeted cleanup
    test_name = request.node.name if hasattr(request, "node") else "unknown"

    # Clean up before test
    ensure_clean_test_environment(test_name)

    yield

    # Clean up after test (optional, but good for preventing accumulation)
    try:
        ensure_clean_test_environment(test_name)
    except Exception as e:
        # Don't fail tests due to cleanup issues
        print(f"Warning: Post-test cleanup failed for {test_name}: {str(e)}")
