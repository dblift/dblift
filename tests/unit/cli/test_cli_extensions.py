import argparse
import tomllib
from argparse import ArgumentParser
from unittest.mock import Mock, patch

from cli._command_handlers import _AVAILABLE_COMMANDS
from cli._parser_setup import create_parser
from cli.extensions import load_command_extensions, load_command_handlers, load_terminal_commands


def test_load_command_extensions_invokes_registered_loader():
    parser = ArgumentParser()
    loader = Mock()
    entry_point = Mock(load=Mock(return_value=loader))

    with patch("cli.extensions.metadata.entry_points", return_value=[entry_point]):
        load_command_extensions(parser)

    loader.assert_called_once_with(parser)


def test_load_command_handlers_merges_registered_handlers():
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"preflight": handler}))

    with patch("cli.extensions.metadata.entry_points", return_value=[entry_point]):
        handlers = load_command_handlers()

    assert handlers == {"preflight": handler}


def test_load_command_handlers_rejects_duplicate_handlers():
    first = Mock()
    second = Mock()
    entry_points = [
        Mock(name="first", load=Mock(return_value=lambda: {"plan": first})),
        Mock(name="second", load=Mock(return_value=lambda: {"plan": second})),
    ]

    with patch("cli.extensions.metadata.entry_points", return_value=entry_points):
        try:
            load_command_handlers()
        except ValueError as exc:
            assert "Duplicate command handler extension: plan" in str(exc)
        else:
            raise AssertionError("duplicate command handlers should be rejected")


def test_load_terminal_commands_merges_registered_commands():
    handler = Mock()
    entry_point = Mock(load=Mock(return_value=lambda: {"license": handler}))

    with patch("cli.extensions.metadata.entry_points", return_value=[entry_point]):
        commands = load_terminal_commands()

    assert commands == {"license": handler}


def test_load_terminal_commands_rejects_duplicate_commands():
    first = Mock()
    second = Mock()
    entry_points = [
        Mock(name="first", load=Mock(return_value=lambda: {"license": first})),
        Mock(name="second", load=Mock(return_value=lambda: {"license": second})),
    ]

    with patch("cli.extensions.metadata.entry_points", return_value=entry_points):
        try:
            load_terminal_commands()
        except ValueError as exc:
            assert "Duplicate terminal command extension: license" in str(exc)
        else:
            raise AssertionError("duplicate terminal commands should be rejected")




    entry_points = pyproject["project"]["entry-points"]
    assert entry_points["dblift.commands"]["builtin"] == (
        "cli.extensions:register_builtin_command_extensions"
    )
    assert entry_points["dblift.command_handlers"]["builtin"] == (
        "cli.extensions:load_builtin_command_handlers"
    )
