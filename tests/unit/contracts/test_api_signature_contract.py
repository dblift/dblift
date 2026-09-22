"""Freeze the parameters of every public ``DBLiftClient`` callable."""

from __future__ import annotations

import inspect
from typing import Iterator

import pytest

from dblift.api import DBLiftClient

from ._snapshot import assert_matches_snapshot

pytestmark = [pytest.mark.unit]


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
            yield f"DBLiftClient.{name} :: {index}:{param.name}|{param.kind.name}|{_default(param)}"


def test_client_signatures_match_snapshot() -> None:
    assert_matches_snapshot("api_signatures", _facts())
