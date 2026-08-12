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

The same probe answers the other half of the question: registering is not the
same as being usable, and ``dblift list-drivers`` must not confuse the two.
``NativeDriverManager.check_driver_installed`` returns ``True`` for any plugin
declaring no ``native_driver_module``, so a Cosmos DB that declared none was
reported "Available" on a machine with no Azure SDK at all — a falsehood the
CLI printed, and one only visible from an environment where ``azure`` is
absent.
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
result["drivers"] = ProviderRegistry.get_available_drivers()
result["cosmosdb_install_extra"] = ProviderRegistry.get_plugin_info("cosmosdb").install_extra

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
    """Every first-party provider registers, cosmosdb included, with ``azure`` unimportable."""
    import tomllib

    result = _run_probe()
    expected = set(
        tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "entry-points"
        ]["dblift.providers"].keys()
    )

    assert result["blocker_effective"], (
        "The probe's import blocker did not take effect, so the run proves "
        "nothing about a machine without the Azure SDK."
    )
    assert "cosmosdb" in result["dialects"], (
        "cosmosdb did not register without the Azure SDK. Its plugin module "
        "must import cleanly on a bare install — the driver is only needed to "
        "connect, not to be discovered."
    )
    assert set(result["dialects"]) == expected, (
        "Discovery registered "
        f"{result['dialects']} with the Azure SDK absent; expected {sorted(expected)}"
    )


def test_the_cosmosdb_plugin_module_itself_imports_without_the_azure_sdk():
    """Registering is not proof that ``plugin.py`` imported — check the metadata.

    ``discover_plugins`` has a filesystem pass that reconstructs a
    ``PluginInfo`` from the package layout when ``plugin.py:PLUGIN`` cannot be
    read. It logs and continues, so a hard ``from azure.cosmos import ...`` at
    the top of ``db/plugins/cosmosdb/plugin.py`` leaves the set above complete
    and the test green — while every field only ``plugin.py`` declares
    (``install_extra``, ``native_driver_module``, ``config_class``) is silently
    lost, taking the driver report and the install hint with it.

    Asserting a declared-only field survived is what distinguishes "cosmosdb
    was registered" from "``plugin.py`` was actually importable".
    """
    result = _run_probe()

    assert result["blocker_effective"], (
        "The probe's import blocker did not take effect, so the run proves "
        "nothing about a machine without the Azure SDK."
    )
    assert result["cosmosdb_install_extra"] == "cosmosdb", (
        "cosmosdb's declared metadata did not survive discovery without the "
        "Azure SDK, so `plugin.py` did not import and the filesystem fallback "
        "registered a degraded plugin in its place."
    )


def test_cosmosdb_is_reported_unavailable_without_the_azure_sdk():
    """``get_available_drivers`` must not call Cosmos DB available with no SDK.

    This is what ``dblift list-drivers`` and ``dblift db diagnose --format
    json`` print, so a wrong answer here is a falsehood shown to the user:
    "cosmosdb : Available" on a machine where the first connect attempt can
    only raise ``ImportError``. The report is only as truthful as the
    plugin's ``native_driver_module`` declaration — a plugin declaring none
    is assumed driverless (correct for SQLite, wrong for Cosmos DB).
    """
    result = _run_probe()

    assert result["blocker_effective"], (
        "The probe's import blocker did not take effect, so the run proves "
        "nothing about a machine without the Azure SDK."
    )
    assert "cosmosdb" in result["drivers"], (
        "cosmosdb is missing from the driver report entirely — the guarantee "
        "under test is that it registers and is reported *unavailable*, not "
        "that it disappears."
    )
    assert result["drivers"]["cosmosdb"] is False, (
        "cosmosdb was reported as an available driver with `azure` "
        "unimportable. `dblift list-drivers` prints this verbatim."
    )
