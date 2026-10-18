"""Canonical encoding of corpus rows and compact facts."""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Any


def dumps(value: Any) -> str:
    """Encode one value as a single canonical JSON line."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _plain(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    return value


def compact_facts(facts: Any) -> Any:
    """Reduce a ``StatementFacts`` to its comparable, JSON-ready form.

    ``None`` and empty fields are dropped; objects are ``[name, type, role, schema]`` in
    reader order; events are sorted.
    """
    out = {}
    for field in dataclasses.fields(facts):
        value = getattr(facts, field.name)
        if field.name == "objects":
            value = [[o.name, o.type.value, o.role, o.schema] for o in value]
        else:
            value = _plain(value)
        if value is None or value == [] or value == {}:
            continue
        out[field.name] = value
    return out
