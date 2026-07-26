"""Plugin discovery must survive an uninstalled optional driver SDK.

``pip install dblift`` ships no database client library — each engine's driver
lives behind its own extra, Cosmos DB's ``azure-cosmos``/``azure-identity``
included. ``ProviderRegistry.discover_plugins()`` nonetheless imports *every*
plugin package on startup, so a bare install imports ``db.plugins.cosmosdb``
with no ``azure`` on the machine. That only works because every ``azure``
import in the tree is function-local or ``TYPE_CHECKING``-guarded, with the one
module-scope exception (``db.plugins.cosmosdb.cosmosdb._sdk``) itself imported
lazily.

That property is invisible in this repo's own test runs: ``azure-cosmos`` is
installed in CI and in every developer environment, so a regression — a new
top-level ``from azure.cosmos import ...`` anywhere the plugin package reaches
on import — would pass the whole suite and only break for users, as an
``ImportError`` during CLI startup that takes out all 19 dialects, not just
Cosmos DB.

The probe therefore runs in a subprocess with a ``sys.meta_path`` finder that
refuses ``azure``, which is the only way to observe the bare-install behaviour
from an environment that has the SDK.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[3]

# Blocks ``azure`` and everything under it, then reports what discovery found.
# ``find_spec`` raising (rather than returning None) also defeats any caller
# that would otherwise fall through to the real, installed distribution.
_PROBE = r"""
import importlib
import json
import sys


class _BlockAzure:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "azure" or fullname.startswith("azure."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


for _name in [m for m in list(sys.modules) if m == "azure" or m.startswith("azure.")]:
    del sys.modules[_name]
sys.meta_path.insert(0, _BlockAzure())

result = {}

try:
    importlib.import_module("azure.cosmos")
    result["blocker_effective"] = False
except ModuleNotFoundError:
    result["blocker_effective"] = True

from db.provider_registry import ProviderRegistry

ProviderRegistry.discover_plugins()
result["dialects"] = sorted(plugin.name for plugin in ProviderRegistry.list_plugins())

print(json.dumps(result))
"""


def _run_probe() -> dict:
    import json

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        "Plugin discovery raised with the Azure SDK unavailable — a bare "
        "`pip install dblift` cannot start.\n"
        f"stderr:\n{completed.stderr}\nstdout:\n{completed.stdout}"
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_discovery_registers_every_dialect_without_the_azure_sdk():
    """All 19 providers register, cosmosdb included, with ``azure`` unimportable."""
    result = _run_probe()

    assert result["blocker_effective"], (
        "The probe's import blocker did not take effect, so the run proves "
        "nothing about a machine without the Azure SDK."
    )
    assert "cosmosdb" in result["dialects"], (
        "cosmosdb did not register without the Azure SDK. Its plugin module "
        "must import cleanly on a bare install — the driver is only needed to "
        "connect, not to be discovered."
    )
    assert len(result["dialects"]) == 19, (
        "Discovery registered "
        f"{len(result['dialects'])} providers instead of 19 with the Azure SDK "
        f"absent: {result['dialects']}"
    )
