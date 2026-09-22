"""Freeze the parameters of every public ``DBLiftClient`` callable."""

from __future__ import annotations

import inspect
from typing import Iterator

import pytest

from dblift.api import DBLiftClient

from ._snapshot import assert_matches_snapshot

pytestmark = [pytest.mark.unit]


def _facts() -> Iterator[str]:
    for name, member in inspect.getmembers(DBLiftClient, predicate=callable):
        if name.startswith("_"):
            continue
        yield f"DBLiftClient.{name} :: <callable>"
        for param in inspect.signature(member).parameters.values():
            if param.name in ("self", "cls"):
                continue
            need = "required" if param.default is inspect.Parameter.empty else "optional"
            yield f"DBLiftClient.{name} :: {param.name}|{param.kind.name}|{need}"


def test_client_signatures_match_snapshot() -> None:
    assert_matches_snapshot("api_signatures", _facts())
