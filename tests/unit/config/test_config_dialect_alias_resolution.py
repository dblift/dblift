"""Plugin ``config_dialect`` aliases must resolve in a fresh interpreter.

``BaseDatabaseConfig._registry`` is filled by import side effects, and plugin
discovery imports every plugin's config class, so an in-process test can pass
purely because discovery already ran.  Resolution is therefore checked in a
clean subprocess that has not discovered any plugin yet.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from dblift.db.provider_registry import ProviderRegistry

_RESOLVE_PROBE = """
import json, sys
from dblift.config.database_config import BaseDatabaseConfig, _resolve_config_class

resolved = {}
for pair in sys.argv[1:]:
    name, parent = pair.split(":")
    cls = _resolve_config_class(BaseDatabaseConfig, name)
    parent_cls = _resolve_config_class(BaseDatabaseConfig, parent)
    resolved[name] = [cls.__name__ if cls else None, parent_cls.__name__ if parent_cls else None]
print(json.dumps(resolved))
"""

_ENGINE_PROBE = """
import sys
from types import SimpleNamespace
from sqlalchemy.engine import make_url
from dblift.api._engine_config import config_from_engine

engine = SimpleNamespace(url=make_url(sys.argv[1]))
config = config_from_engine(engine)
print(config.database.type, config.database.host, config.database.database)
"""


def _registered_aliases() -> list[str]:
    return sorted(p.name for p in ProviderRegistry.list_plugins() if p.config_dialect)


def _parent_of(alias: str) -> str:
    plugin = ProviderRegistry.get_plugin_info(alias)
    assert plugin is not None and plugin.config_dialect
    return plugin.config_dialect


def _run_fresh(code: str, *args: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def fresh_interpreter_resolution() -> dict[str, list[str | None]]:
    pairs = [f"{alias}:{_parent_of(alias)}" for alias in _registered_aliases()]
    return json.loads(_run_fresh(_RESOLVE_PROBE, *pairs))


def test_there_are_aliases_to_check():
    assert "mariadb" in _registered_aliases()


@pytest.mark.parametrize("alias", _registered_aliases())
def test_alias_resolves_in_fresh_interpreter(alias, fresh_interpreter_resolution):
    resolved, parent_resolved = fresh_interpreter_resolution[alias]
    assert parent_resolved, f"parent {_parent_of(alias)!r} of {alias!r} has no config class"
    assert resolved == parent_resolved


@pytest.mark.parametrize(
    "url, expected",
    [
        ("mariadb+pymysql://u:p@h:3306/db", "mariadb h db"),
        ("cockroachdb://u:p@h:26257/db", "cockroachdb h db"),
    ],
)
def test_alias_sqlalchemy_url_keeps_alias_type_in_fresh_interpreter(url, expected):
    # A stand-in engine avoids needing the driver just to build a config.
    assert _run_fresh(_ENGINE_PROBE, url) == expected


def test_self_referencing_alias_returns_none_instead_of_recursing():
    from types import SimpleNamespace
    from unittest.mock import patch

    from dblift.config.database_config import BaseDatabaseConfig, _resolve_config_class

    plugin = SimpleNamespace(config_class=None, config_dialect="loopdb")
    with patch.object(ProviderRegistry, "get_plugin_info", return_value=plugin):
        assert _resolve_config_class(BaseDatabaseConfig, "loopdb") is None


def test_two_plugin_alias_cycle_returns_none_instead_of_recursing():
    from types import SimpleNamespace
    from unittest.mock import patch

    from dblift.config.database_config import BaseDatabaseConfig, _resolve_config_class

    plugins = {
        "a": SimpleNamespace(config_class=None, config_dialect="b"),
        "b": SimpleNamespace(config_class=None, config_dialect="a"),
    }
    with patch.object(ProviderRegistry, "get_plugin_info", side_effect=plugins.get):
        assert _resolve_config_class(BaseDatabaseConfig, "a") is None
