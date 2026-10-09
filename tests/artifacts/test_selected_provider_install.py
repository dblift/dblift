"""Legacy aliases and modern descriptors work in a fresh installed environment."""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.artifacts._clean_source import archived_source

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "artifacts" / "fixtures"


@pytest.mark.parametrize("first", ["legacy_alias_provider", "modern_descriptor_provider"])
def test_installed_legacy_alias_and_modern_descriptor_resolve_in_either_order(tmp_path, first):
    source = archived_source(ROOT, tmp_path / "source")
    build = tmp_path / "build"
    build.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(build), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    environment = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(environment)],
        check=True,
        capture_output=True,
        text=True,
    )
    python = environment / "bin" / "python"
    wheel = next(build.glob("dblift-*.whl"))
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    second = (
        "modern_descriptor_provider"
        if first == "legacy_alias_provider"
        else "legacy_alias_provider"
    )
    for fixture in (first, second):
        subprocess.run(
            [str(python), "-m", "pip", "install", str(FIXTURES / fixture)],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        [str(python), "-m", "pip", "check"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
import sys
from pathlib import Path
from dblift.db.provider_registry import ProviderRegistry

first, second = sys.argv[1:]
for alias in (first, second):
    plugin = ProviderRegistry.get_plugin_info(alias)
    assert plugin is not None, alias
    assert plugin is ProviderRegistry.get_plugin_info(alias)
assert ProviderRegistry.get_plugin_info('legacy_alias').name == 'legacy_fixture'
assert ProviderRegistry.get_plugin_info('modern_alias').name == 'modern_fixture'
for module in ('oracle', 'postgresql', 'mongodb', 'snowflake'):
    assert f'dblift.db.plugins.{module}.provider' not in sys.modules
for name, module in sys.modules.items():
    if name == 'dblift' or name.startswith(('dblift.', 'legacy_alias_provider', 'modern_descriptor_provider')):
        origin = getattr(module, '__file__', None)
        if origin:
            assert Path(origin).resolve().is_relative_to(sys.prefix), origin
"""
    aliases = (
        ("legacy_alias", "modern_alias")
        if first == "legacy_alias_provider"
        else ("modern_alias", "legacy_alias")
    )
    run = subprocess.run(
        [str(python), "-I", "-c", script, *aliases],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
