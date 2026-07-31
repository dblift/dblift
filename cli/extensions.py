"""CLI extension loading through installed package entry points."""

import os
from argparse import ArgumentParser
from importlib import metadata
from typing import Any, Callable, Dict

COMMAND_ENTRY_POINT_GROUP = "dblift.commands"
HANDLER_ENTRY_POINT_GROUP = "dblift.command_handlers"
TERMINAL_ENTRY_POINT_GROUP = "dblift.terminal_commands"
CommandHandler = Callable[[Any], tuple[bool, Any]]
TerminalCommand = Callable[[Any], int]


def _extensions_disabled() -> bool:
    return os.environ.get("DBLIFT_DISABLE_CLI_EXTENSIONS") == "1"


def load_command_extensions(parser: ArgumentParser) -> None:
    """Register CLI command parsers provided by installed extensions."""
    if _extensions_disabled():
        return
    for entry_point in metadata.entry_points(group=COMMAND_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loader(parser)


def load_command_handlers() -> Dict[str, CommandHandler]:
    """Load command handlers provided by installed extensions."""
    handlers: Dict[str, CommandHandler] = {}
    if _extensions_disabled():
        return handlers
    for entry_point in metadata.entry_points(group=HANDLER_ENTRY_POINT_GROUP):
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
    if _extensions_disabled():
        return commands
    for entry_point in metadata.entry_points(group=TERMINAL_ENTRY_POINT_GROUP):
        loader = entry_point.load()
        loaded = loader()
        for command, handler in loaded.items():
            if command in commands:
                raise ValueError(f"Duplicate terminal command extension: {command}")
            commands[command] = handler
    return commands
