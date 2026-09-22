"""Freeze the CLI surface: every subcommand, flag and positional."""

from __future__ import annotations

import argparse
from typing import Iterator

import pytest

from ._snapshot import assert_matches_snapshot

pytestmark = [pytest.mark.unit]


def _default(action: argparse.Action) -> str:
    default = action.default
    if default is argparse.SUPPRESS:
        return "suppress"
    if isinstance(default, (str, int, float, bool, type(None))):
        return repr(default)
    return "<object>"


def _facts(parser: argparse.ArgumentParser, path: str = "<root>") -> Iterator[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                child = name if path == "<root>" else f"{path} {name}"
                yield f"{child} :: <command>"
                yield from _facts(sub, child)
            continue
        choices = sorted(map(str, action.choices)) if action.choices else None
        shape = f"{type(action).__name__}|nargs={action.nargs}|choices={choices}|default={_default(action)}"
        if action.option_strings:
            for option in action.option_strings:
                yield f"{path} :: {option}"
                yield f"{path} :: {option} :: {shape}"
        else:
            yield f"{path} :: <positional> {action.dest}"
            yield f"{path} :: <positional> {action.dest} :: {shape}"


def test_cli_surface_matches_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    # Installed extension packages add their own commands; the contract
    # recorded here is the surface of this distribution alone.
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")
    from dblift.cli._parser_setup import create_parser

    assert_matches_snapshot("cli_surface", _facts(create_parser()))
