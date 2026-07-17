"""Tests for the premium-command stubs surfaced in the OSS CLI.

Covers the three stub surfaces:
* parser stubs (``--help`` visibility, entry-point precedence),
* the ``cli/main.py`` first-position short-circuit (message + exit code),
* the gap-fill handlers used by chained invocations.
"""

import argparse
from argparse import ArgumentParser
from unittest.mock import Mock

import pytest

from cli._command_handlers import _AVAILABLE_COMMANDS, _COMMAND_HANDLERS, PREMIUM_STUB_COMMANDS
from cli._constants import EXIT_LICENSE_REQUIRED
from cli._parser_setup import _register_premium_stub_parsers, create_parser
from cli.premium_manifest import (
    PREMIUM_COMMANDS,
    UPGRADE_URL,
    premium_commands_missing_from,
    premium_stub_index,
    render_upsell,
)


def test_exit_code_is_distinct_from_failure_and_usage_codes():
    assert EXIT_LICENSE_REQUIRED not in {0, 1, 2, 130}


def test_manifest_names_are_unique():
    names = [cmd.name for cmd in PREMIUM_COMMANDS]
    assert len(names) == len(set(names))


def test_missing_from_excludes_registered_names():
    registered = {"diff", "data"}
    missing = {cmd.name for cmd in premium_commands_missing_from(registered)}
    assert "diff" not in missing
    assert "data" not in missing
    assert "plan" in missing


def test_stub_index_empty_when_everything_registered():
    assert premium_stub_index({cmd.name for cmd in PREMIUM_COMMANDS}) == {}


def test_render_upsell_names_command_edition_and_url():
    for cmd in PREMIUM_COMMANDS:
        message = render_upsell(cmd)
        assert f"'{cmd.name}'" in message
        assert cmd.edition in message
        assert UPGRADE_URL in message


def test_help_lists_every_stub_with_edition_label():
    help_text = create_parser().format_help()
    for cmd in PREMIUM_COMMANDS:
        if cmd.name not in PREMIUM_STUB_COMMANDS:
            continue  # a real extension owns this name in this environment
        assert cmd.name in help_text
        assert f"[{cmd.edition}]" in help_text


def test_register_stub_parsers_never_overrides_existing_subparser():
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    real_diff = subparsers.add_parser("diff", help="real extension diff")

    _register_premium_stub_parsers(parser)

    assert subparsers.choices["diff"] is real_diff
    # Every other manifest command received a stub.
    for cmd in PREMIUM_COMMANDS:
        assert cmd.name in subparsers.choices


def test_register_stub_parsers_noop_without_subparsers():
    parser = ArgumentParser()
    _register_premium_stub_parsers(parser)  # must not raise


def test_stub_parser_accepts_arbitrary_arguments():
    parser = ArgumentParser()
    parser.add_subparsers(dest="command")
    _register_premium_stub_parsers(parser)

    args = parser.parse_args(["preflight", "positional", "value"])
    assert args.command == "preflight"


def test_stub_commands_are_available_commands():
    for name in PREMIUM_STUB_COMMANDS:
        assert name in _AVAILABLE_COMMANDS


def test_gap_fill_handler_logs_upsell_and_fails():
    for name, cmd in PREMIUM_STUB_COMMANDS.items():
        handler = _COMMAND_HANDLERS[name]
        ctx = Mock()
        success, result = handler(ctx)
        assert success is False
        assert result is None
        logged = ctx.log.error.call_args[0][0]
        assert UPGRADE_URL in logged
        assert cmd.edition in logged


@pytest.mark.parametrize(
    "argv",
    [
        ["diff"],
        ["diff", "--snapshot-model", "model.json"],
        ["plan"],
        ["data", "undo", "42", "--dataset", "ds"],
        ["export-schema", "--help"],
    ],
)
def test_main_short_circuits_stub_with_license_exit_code(monkeypatch, capsys, argv):
    if argv[0] not in PREMIUM_STUB_COMMANDS:
        pytest.skip("a real extension owns this command in this environment")
    import cli.main as cli_main

    monkeypatch.setattr("sys.argv", ["dblift"] + argv)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()

    assert excinfo.value.code == EXIT_LICENSE_REQUIRED
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert UPGRADE_URL in output
    assert f"'{argv[0]}'" in output


def test_main_short_circuit_runs_before_config_and_db_load(monkeypatch):
    if "diff" not in PREMIUM_STUB_COMMANDS:
        pytest.skip("a real extension owns 'diff' in this environment")
    import cli.main as cli_main

    monkeypatch.setattr("sys.argv", ["dblift", "diff"])
    load_config = Mock(side_effect=AssertionError("config load must not run for a stub"))
    monkeypatch.setattr(cli_main, "_load_and_merge_config", load_config)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()

    assert excinfo.value.code == EXIT_LICENSE_REQUIRED
    load_config.assert_not_called()
