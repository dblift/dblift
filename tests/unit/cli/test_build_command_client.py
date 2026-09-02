"""The CLI client build honors the config-only marker and the client seam."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import dblift.cli.main as cli_main
from dblift.cli.handlers._shared import ConfigOnlyClient
from dblift.core.seams import client_factory

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    client_factory._reset_for_tests()
    monkeypatch.setattr(client_factory, "entry_points", lambda group: [])
    yield
    client_factory._reset_for_tests()


def _ctx(commands):
    return SimpleNamespace(commands=commands, config=SimpleNamespace(), log=None)


def _marked_handler():
    def handler(ctx):  # pragma: no cover - never called
        raise NotImplementedError

    handler._dblift_config_only_client = True
    return handler


def test_marked_single_command_gets_config_only_client(monkeypatch):
    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {"plan": _marked_handler()})
    ctx = _ctx(["plan"])
    client = cli_main._build_command_client(ctx)
    assert isinstance(client, ConfigOnlyClient)
    assert client.config is ctx.config


def test_unmarked_command_gets_resolved_client(monkeypatch):
    built = []

    class _SeamClient:
        @classmethod
        def from_config(cls, config, logger=None):
            built.append(config)
            return cls()

    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {"migrate": lambda ctx: None})
    monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _SeamClient)
    ctx = _ctx(["migrate"])
    client = cli_main._build_command_client(ctx)
    assert isinstance(client, _SeamClient)
    assert built == [ctx.config]


def test_multi_command_run_never_goes_config_only(monkeypatch):
    class _SeamClient:
        @classmethod
        def from_config(cls, config, logger=None):
            return cls()

    monkeypatch.setattr(
        cli_main, "_COMMAND_HANDLERS", {"plan": _marked_handler(), "migrate": lambda ctx: None}
    )
    monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _SeamClient)
    client = cli_main._build_command_client(_ctx(["plan", "migrate"]))
    assert isinstance(client, _SeamClient)


def test_unknown_command_defaults_to_resolved_client(monkeypatch):
    class _SeamClient:
        @classmethod
        def from_config(cls, config, logger=None):
            return cls()

    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {})
    monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _SeamClient)
    client = cli_main._build_command_client(_ctx(["plan"]))
    assert isinstance(client, _SeamClient)
