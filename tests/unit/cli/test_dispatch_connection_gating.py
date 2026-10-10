"""Handlers can gate the pre-command connection and refuse before it opens."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import dblift.cli.main as cli_main
from dblift.api.client import DBLiftClient
from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.cli._output import CommandOutput
from dblift.config import DbliftConfig
from dblift.core.seams.capabilities import CapabilityDeniedError

pytestmark = [pytest.mark.unit]


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "gate.db"


def _dispatch(monkeypatch, db_file, handler, log=None):
    """Run ``_dispatch_command`` for a registered fake ``probe`` command on SQLite."""
    config = DbliftConfig.from_dict(
        {"database": {"url": f"sqlite:///{db_file}", "type": "sqlite"}, "migrations": {}}
    )
    log = log or MagicMock()
    ctx = cli_main._CliContext(
        commands=["probe"],
        global_arguments=[],
        subcommand_args=[],
        args=SimpleNamespace(strict_mode=False, mode="files"),
        parser=MagicMock(),
        log=log,
        config=config,
    )
    monkeypatch.setitem(cli_main._COMMAND_HANDLERS, "probe", handler)
    monkeypatch.setattr(
        cli_main,
        "_build_command_client",
        lambda c: DBLiftClient.from_config(c.config, logger=log),
    )
    with (
        patch.object(cli_main, "_resolve_scripts_directories", return_value=(None, [], False, {})),
        patch.object(cli_main, "_collect_placeholders", return_value={}),
    ):
        return cli_main._dispatch_command(ctx, CommandOutput("table")), log


def _handler(calls):
    def handler(ctx):
        calls.append(ctx.args)
        return True, None

    return handler


def test_handler_without_attributes_connects_before_running(monkeypatch, db_file):
    calls = []
    code, _ = _dispatch(monkeypatch, db_file, _handler(calls))
    assert code == 0 and len(calls) == 1
    assert db_file.exists()


def test_predicate_false_skips_connection(monkeypatch, db_file):
    calls = []
    handler = _handler(calls)
    handler._dblift_needs_connection = lambda args: args.mode != "files"
    code, _ = _dispatch(monkeypatch, db_file, handler)
    assert code == 0 and len(calls) == 1
    assert not db_file.exists()


def test_predicate_true_connects(monkeypatch, db_file):
    calls = []
    handler = _handler(calls)
    handler._dblift_needs_connection = lambda args: args.mode == "files"
    code, _ = _dispatch(monkeypatch, db_file, handler)
    assert code == 0 and len(calls) == 1
    assert db_file.exists()


def test_pre_connection_check_denial_refuses_before_connecting(monkeypatch, db_file):
    calls = []
    handler = _handler(calls)

    def deny(args, license_tier):
        raise CapabilityDeniedError("needs a license")

    handler._dblift_pre_connection_check = deny
    with pytest.raises(SystemExit) as excinfo:
        _dispatch(monkeypatch, db_file, handler)
    assert excinfo.value.code == EXIT_LICENSE_REQUIRED
    assert calls == []
    assert not db_file.exists()


def test_pre_connection_denial_reports_like_in_handler_denial(monkeypatch, db_file, tmp_path):
    def raising_handler(ctx):
        raise CapabilityDeniedError("needs a license")

    pre = _handler([])
    pre._dblift_pre_connection_check = MagicMock(
        side_effect=CapabilityDeniedError("needs a license")
    )
    outcomes = []
    for handler, path in ((raising_handler, tmp_path / "a.db"), (pre, db_file)):
        log = MagicMock()
        with pytest.raises(SystemExit) as excinfo:
            _dispatch(monkeypatch, path, handler, log=log)
        outcomes.append((excinfo.value.code, log.error.call_args_list))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == EXIT_LICENSE_REQUIRED


def test_pre_connection_check_passing_still_connects(monkeypatch, db_file):
    calls = []
    handler = _handler(calls)
    seen = []
    handler._dblift_pre_connection_check = lambda args, license_tier: seen.append(license_tier)
    code, _ = _dispatch(monkeypatch, db_file, handler)
    assert code == 0 and len(calls) == 1 and seen == [None]
    assert db_file.exists()
