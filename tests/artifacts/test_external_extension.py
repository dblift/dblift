"""Prove provider and event registration from separately installed wheels."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
PROBE = Path(__file__).with_name("installed_extension_probe.py")


def _run(args, cwd):
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("DBLIFT_DISABLE_CLI_EXTENSIONS", None)
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def wheels(tmp_path_factory):
    wheel_dir = tmp_path_factory.mktemp("extension-wheels")
    for source in (ROOT, FIXTURES / "lightweight_extension", FIXTURES / "lightweight_listener"):
        result = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
                str(source),
            ],
            wheel_dir,
        )
        assert result.returncode == 0, result.stderr
    return {
        name: next(wheel_dir.glob(pattern))
        for name, pattern in {
            "dblift": "dblift-[0-9]*.whl",
            "provider": "dblift_lightweight_fixture-*.whl",
            "listener": "dblift_lightweight_listener_fixture-*.whl",
        }.items()
    }


@pytest.mark.parametrize("order", [("provider", "listener"), ("listener", "provider")])
def test_installed_extension_adds_provider_and_independent_listeners(wheels, tmp_path, order):
    environment = tmp_path / "env"
    result = _run([sys.executable, "-m", "venv", str(environment)], tmp_path)
    assert result.returncode == 0, result.stderr
    python = environment / "bin" / "python"
    result = _run([str(python), "-m", "pip", "install", str(wheels["dblift"])], tmp_path)
    assert result.returncode == 0, result.stderr

    before = _run([str(python), "-I", str(PROBE), "before"], tmp_path)
    assert before.returncode == 0, before.stderr
    for name in order:
        installed = _run([str(python), "-m", "pip", "install", str(wheels[name])], tmp_path)
        assert installed.returncode == 0, installed.stderr
    after = _run([str(python), "-I", str(PROBE), "after"], tmp_path)
    assert after.returncode == 0, after.stderr


@pytest.mark.parametrize(
    "source",
    [
        FIXTURES / "lightweight_extension" / "fixture_sqlite" / "__init__.py",
        FIXTURES / "lightweight_listener" / "fixture_listener" / "__init__.py",
    ],
)
def test_fixture_imports_stay_on_public_extension_surface(source):
    allowed = {"dblift.api.events"}
    if source.parent.name == "fixture_sqlite":
        allowed.update(
            {
                "dblift.extensions.providers",
                # The provider fixture delegates database work to the existing SQLite engine.
                "dblift.db.plugins.sqlite.plugin",
            }
        )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert set(imports) <= allowed
    assert not any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id in {"__import__", "import_module"}
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
        )
        for node in ast.walk(tree)
    )
