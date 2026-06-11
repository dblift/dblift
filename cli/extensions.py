"""CLI extension loading through installed package entry points."""

from argparse import ArgumentParser
from importlib import metadata
from typing import Any, Callable, Dict

COMMAND_ENTRY_POINT_GROUP = "dblift.commands"
HANDLER_ENTRY_POINT_GROUP = "dblift.command_handlers"
TERMINAL_ENTRY_POINT_GROUP = "dblift.terminal_commands"
CommandExtension = Callable[[ArgumentParser], None]
CommandHandler = Callable[[Any], tuple[bool, Any]]
TerminalCommand = Callable[[Any], int]
_BUILTIN_COMMAND_EXTENSION = "cli.extensions:register_builtin_command_extensions"
_BUILTIN_COMMAND_HANDLERS = "cli.extensions:load_builtin_command_handlers"


def _entry_point_value(entry_point: Any) -> str:
    return str(getattr(entry_point, "value", ""))


def register_builtin_command_extensions(parser: ArgumentParser) -> None:
    """Register first-party command parsers kept in the OSS package."""
    from cli._parser_setup import _register_builtin_command_parsers

    _register_builtin_command_parsers(parser)


def load_builtin_command_handlers() -> Dict[str, CommandHandler]:
    """Return first-party command handlers kept in the OSS package.

    Additional commands can be installed as entry-point extensions.
    """
    return {}


def load_command_extensions(parser: ArgumentParser) -> None:
    """Register CLI command parsers provided by installed extensions."""
    for entry_point in metadata.entry_points(group=COMMAND_ENTRY_POINT_GROUP):
        if _entry_point_value(entry_point) == _BUILTIN_COMMAND_EXTENSION:
            continue
        loader = entry_point.load()
        loader(parser)


def load_command_handlers() -> Dict[str, CommandHandler]:
    """Load command handlers provided by installed extensions."""
    handlers: Dict[str, CommandHandler] = {}
    for entry_point in metadata.entry_points(group=HANDLER_ENTRY_POINT_GROUP):
        if _entry_point_value(entry_point) == _BUILTIN_COMMAND_HANDLERS:
            continue
        loader = entry_point.load()
        loaded = loader()
        for command, handler in loaded.items():
            if command in handlers:
                raise ValueError(f"Duplicate command handler extension: {command}")
            handlers[command] = handler
    return handlers


def load_terminal_commands() -> Dict[str, TerminalCommand]:
    """Load terminal commands provided by installed extensions."""
    commands: Dict[str, TerminalCommand] = {}
    for entry_point in metadata.entry_points(group=TERMINAL_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loaded = loader()
        for command, handler in loaded.items():
            if command in commands:
                raise ValueError(f"Duplicate terminal command extension: {command}")
            commands[command] = handler
    return commands
