"""Freeze the parameters of every public ``DBLiftClient`` callable.

A parameter's position is recorded only when it can be passed by position:
for keyword-only and variadic parameters no caller can rely on it.
"""

from __future__ import annotations

import inspect
from typing import Iterator

import pytest

from dblift.api import DBLiftClient

from ._snapshot import assert_matches_snapshot

pytestmark = [pytest.mark.unit]

_POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def _default(param: inspect.Parameter) -> str:
    if param.default is inspect.Parameter.empty:
        return "required"
    if isinstance(param.default, (str, int, float, bool, type(None), tuple)):
        return f"default={param.default!r}"
    return "default=<object>"


def _facts() -> Iterator[str]:
    for name, member in inspect.getmembers(DBLiftClient, predicate=callable):
        if name.startswith("_"):
            continue
        yield f"DBLiftClient.{name} :: <callable>"
        params = [
            p
            for p in inspect.signature(member).parameters.values()
            if p.name not in ("self", "cls")
        ]
        for index, param in enumerate(params):
            fact = f"{param.name}|{param.kind.name}|{_default(param)}"
            if param.kind in _POSITIONAL:
                fact = f"{index}:{fact}"
            yield f"DBLiftClient.{name} :: {fact}"


def test_client_signatures_match_snapshot() -> None:
    assert_matches_snapshot("api_signatures", _facts())
