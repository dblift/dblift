"""A capability denial raised while the configuration loads exits with EXIT_LICENSE_REQUIRED.

A secrets provider registered through ``register_provider`` may refuse to
resolve a reference with a ``CapabilityDeniedError``. The CLI loads the
configuration, and resolves its secret references, before command dispatch,
so the denial is reported there: one line on stderr and the same exit code as
a denial at dispatch. ``dblift mcp`` reports the same exit code.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
import yaml

import dblift.config.secrets._registry as secrets_registry
from dblift.cli._config_helpers import _load_and_merge_config
from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.cli.mcp.runner import CommandInvocationError, run_command
from dblift.config.secrets import AbstractSecretsProvider, SecretsResolutionError, clear_cache
from dblift.core.seams.capabilities import CapabilityDeniedError

pytestmark = [pytest.mark.unit]

_MESSAGE = "Reading secrets from deny-test requires a capability that is not available."


class _Denied(CapabilityDeniedError):
    pass


class _DeniedResolution(CapabilityDeniedError, SecretsResolutionError):
    """A refusal that is also a resolution error is still reported as a denial."""


def _provider(error: type) -> type:
    class _RefusingProvider(AbstractSecretsProvider):
        scheme = "deny-test"

        def is_available(self) -> bool:
            return True

        def resolve(self, uri: str) -> str:
            raise error(_MESSAGE)

    return _RefusingProvider


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


def _register(monkeypatch, error: type) -> None:
    monkeypatch.setitem(secrets_registry._providers, "deny-test", _provider(error))


def _config_file(tmp_path: Path, password: str = "plain") -> Path:
    (tmp_path / "migrations").mkdir(exist_ok=True)
    path = tmp_path / "dblift.yaml"
    data: Dict[str, Any] = {
        "database": {"url": f"sqlite:///{tmp_path / 'test.db'}", "password": password},
        "migrations": {"directories": [{"path": str(tmp_path / "migrations")}]},
    }
    path.write_text(yaml.safe_dump(data))
    return path


def _args(config: Path, **overrides: Any) -> SimpleNamespace:
    values: Dict[str, Any] = {
        "config": str(config),
        "command": "info",
        "commands_list": ["info"],
        "database_url": None,
        "database_username": None,
        "database_password": None,
        "database_schema": None,
        "table_name": None,
        "snapshot_table": None,
        "installed_by": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("error", [_Denied, _DeniedResolution])
def test_denial_in_the_config_file_exits_with_the_capability_code(
    tmp_path, monkeypatch, capsys, error
):
    _register(monkeypatch, error)
    config = _config_file(tmp_path, password="deny-test://db")

    with pytest.raises(SystemExit) as exited:
        _load_and_merge_config(_args(config), None)

    assert exited.value.code == EXIT_LICENSE_REQUIRED
    err = capsys.readouterr().err
    assert err.strip() == f"Error: {_MESSAGE}"


@pytest.mark.parametrize("error", [_Denied, _DeniedResolution])
def test_denial_in_a_database_override_exits_with_the_capability_code(
    tmp_path, monkeypatch, capsys, error
):
    _register(monkeypatch, error)
    config = _config_file(tmp_path)

    with pytest.raises(SystemExit) as exited:
        _load_and_merge_config(_args(config, database_password="deny-test://db"), None)

    assert exited.value.code == EXIT_LICENSE_REQUIRED
    assert capsys.readouterr().err.strip() == f"Error: {_MESSAGE}"


def test_a_resolution_error_still_exits_1(tmp_path, monkeypatch, capsys):
    _register(monkeypatch, SecretsResolutionError)
    config = _config_file(tmp_path, password="deny-test://db")

    with pytest.raises(SystemExit) as exited:
        _load_and_merge_config(_args(config), None)

    assert exited.value.code == 1
    assert capsys.readouterr().err.strip() == f"Error: {_MESSAGE}"


@pytest.mark.parametrize("error", [_Denied, _DeniedResolution])
def test_mcp_reports_the_capability_code(tmp_path, monkeypatch, error):
    _register(monkeypatch, error)
    config = _config_file(tmp_path, password="deny-test://db")

    with pytest.raises(CommandInvocationError) as raised:
        run_command(["--config", str(config)], "info", [])

    assert raised.value.exit_code == EXIT_LICENSE_REQUIRED
    assert _MESSAGE in str(raised.value)


def test_mcp_server_start_reports_a_denial_and_still_serves(tmp_path, monkeypatch, capsys):
    """At start the server only announces its target; each tool call reports its own error."""
    from argparse import Namespace
    from unittest.mock import MagicMock, patch

    from dblift.cli.handlers._shared import CliCommandContext
    from dblift.cli.handlers.mcp import _handle_mcp

    _register(monkeypatch, _Denied)
    config = _config_file(tmp_path, password="deny-test://db")
    server = MagicMock()
    for method in (
        "tool_names",
        "skipped_tools",
        "unmatched_allowed_tools",
        "connection_bound_tools",
        "connection_bound_resources",
        "resource_names",
        "skipped_resources",
        "unmatched_allowed_resources",
    ):
        getattr(server, method).return_value = []
    args = Namespace(
        config=str(config),
        env=None,
        global_arguments=[],
        read_only=False,
        offline=False,
        mode="author",
        tools=None,
        resources=None,
    )

    with patch("dblift.cli.mcp.server.build_server", return_value=server):
        assert _handle_mcp(CliCommandContext(args=args)) == (True, None)

    assert "configuration not loaded at start" in capsys.readouterr().err
    server.run_stdio.assert_called_once_with()


@pytest.mark.parametrize("subcommand", ["validate-config", "check-connection"])
@pytest.mark.parametrize("error", [_Denied, _DeniedResolution])
def test_db_subcommands_exit_with_the_capability_code(
    tmp_path, monkeypatch, capsys, subcommand, error
):
    """``db`` subcommands load the configuration themselves; a denial there exits 4 too."""
    from dblift.cli import main as cli_main

    _register(monkeypatch, error)
    config = _config_file(tmp_path, password="deny-test://db")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["dblift", "db", subcommand, "--config", str(config)])

    with pytest.raises(SystemExit) as exited:
        cli_main.main()

    assert exited.value.code == EXIT_LICENSE_REQUIRED
    err = capsys.readouterr().err
    assert _MESSAGE in err
    assert "Traceback" not in err


def test_an_empty_denial_message_is_replaced_by_the_fallback(tmp_path, monkeypatch, capsys):
    from dblift.cli._constants import LICENSE_REQUIRED_FALLBACK_MESSAGE

    class _Silent(AbstractSecretsProvider):
        scheme = "deny-test"

        def is_available(self) -> bool:
            return True

        def resolve(self, uri: str) -> str:
            raise CapabilityDeniedError("")

    monkeypatch.setitem(secrets_registry._providers, "deny-test", _Silent)
    config = _config_file(tmp_path, password="deny-test://db")

    with pytest.raises(SystemExit) as exited:
        _load_and_merge_config(_args(config), None)

    assert exited.value.code == EXIT_LICENSE_REQUIRED
    assert capsys.readouterr().err.strip() == f"Error: {LICENSE_REQUIRED_FALLBACK_MESSAGE}"


def test_validate_config_without_a_config_file_exits_with_the_capability_code(
    tmp_path, monkeypatch, capsys
):
    from dblift.cli import main as cli_main

    _register(monkeypatch, _Denied)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DBLIFT_DB_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "deny-test://db")
    monkeypatch.setattr("sys.argv", ["dblift", "db", "validate-config"])

    with pytest.raises(SystemExit) as exited:
        cli_main.main()

    assert exited.value.code == EXIT_LICENSE_REQUIRED
    assert _MESSAGE in capsys.readouterr().err
