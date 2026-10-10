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
for name in sys.argv[1:]:
    cls = _resolve_config_class(BaseDatabaseConfig, name)
    resolved[name] = cls.__name__ if cls else None
print(json.dumps(resolved))
"""

_ENGINE_PROBE = """
from types import SimpleNamespace
from sqlalchemy.engine import make_url
from dblift.api._engine_config import config_from_engine

engine = SimpleNamespace(url=make_url("mariadb+pymysql://u:p@h:3306/db"))
config = config_from_engine(engine)
print(config.database.type, config.database.host, config.database.database)
"""


def _registered_aliases() -> list[str]:
    return sorted(p.name for p in ProviderRegistry.list_plugins() if p.config_dialect)


def _run_fresh(code: str, *args: str) -> str:
    return subprocess.run(
        [sys.executable, "-c", code, *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def fresh_interpreter_resolution() -> dict[str, str | None]:
    return json.loads(_run_fresh(_RESOLVE_PROBE, *_registered_aliases()))


def test_there_are_aliases_to_check():
    assert "mariadb" in _registered_aliases()


@pytest.mark.parametrize("alias", _registered_aliases())
def test_alias_resolves_in_fresh_interpreter(alias, fresh_interpreter_resolution):
    assert fresh_interpreter_resolution[alias], f"{alias!r} has no config class"


def test_mariadb_sqlalchemy_url_yields_mariadb_config_in_fresh_interpreter():
    # A stand-in engine avoids needing the PyMySQL driver just to build a config.
    assert _run_fresh(_ENGINE_PROBE) == "mariadb h db"


def test_self_referencing_alias_returns_none_instead_of_recursing():
    from types import SimpleNamespace
    from unittest.mock import patch

    from dblift.config.database_config import BaseDatabaseConfig, _resolve_config_class

    plugin = SimpleNamespace(config_class=None, config_dialect="loopdb")
    with patch.object(ProviderRegistry, "get_plugin_info", return_value=plugin):
        assert _resolve_config_class(BaseDatabaseConfig, "loopdb") is None
