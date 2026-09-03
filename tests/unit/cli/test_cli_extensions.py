import argparse
import tomllib
from argparse import ArgumentParser
from unittest.mock import Mock, patch

from dblift.cli._command_handlers import _AVAILABLE_COMMANDS
from dblift.cli._parser_setup import create_parser
from dblift.cli.extensions import (
    load_command_extensions,
    load_command_handlers,
    load_terminal_commands,
)


def test_load_command_extensions_invokes_registered_loader():
    parser = ArgumentParser()
    loader = Mock()
    entry_point = Mock(load=Mock(return_value=loader))

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        load_command_extensions(parser)

    loader.assert_called_once_with(parser)


def test_load_command_extensions_skips_entrypoints_when_disabled(monkeypatch):
    parser = ArgumentParser()
    loader = Mock()
    entry_point = Mock(load=Mock(return_value=loader))
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        load_command_extensions(parser)

    entry_point.load.assert_not_called()
    loader.assert_not_called()


def test_load_command_handlers_merges_registered_handlers():
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"sample": handler}))

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        handlers = load_command_handlers()

    assert handlers == {"sample": handler}


def test_load_command_handlers_skips_entrypoints_when_disabled(monkeypatch):
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"sample": handler}))
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        handlers = load_command_handlers()

    assert handlers == {}
    entry_point.load.assert_not_called()


def test_load_command_handlers_rejects_duplicate_handlers():
    first = Mock()
    second = Mock()
    entry_points = [
        Mock(name="first", load=Mock(return_value=lambda: {"sample": first})),
        Mock(name="second", load=Mock(return_value=lambda: {"sample": second})),
    ]

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=entry_points):
        try:
            load_command_handlers()
        except ValueError as exc:
            assert "Duplicate command handler extension: sample" in str(exc)
        else:
            raise AssertionError("duplicate command handlers should be rejected")


def test_load_terminal_commands_merges_registered_commands():
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"sample": handler}))

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        commands = load_terminal_commands()

    assert commands == {"sample": handler}


def test_load_terminal_commands_skips_entrypoints_when_disabled(monkeypatch):
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"sample": handler}))
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=[entry_point]):
        commands = load_terminal_commands()

    assert commands == {}
    entry_point.load.assert_not_called()


def test_load_terminal_commands_rejects_duplicate_commands():
    first = Mock()
    second = Mock()
    entry_points = [
        Mock(name="first", load=Mock(return_value=lambda: {"sample": first})),
        Mock(name="second", load=Mock(return_value=lambda: {"sample": second})),
    ]

    with patch("dblift.cli.extensions.metadata.entry_points", return_value=entry_points):
        try:
            load_terminal_commands()
        except ValueError as exc:
            assert "Duplicate terminal command extension: sample" in str(exc)
        else:
            raise AssertionError("duplicate terminal commands should be rejected")
