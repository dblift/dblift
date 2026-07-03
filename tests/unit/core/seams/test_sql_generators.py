"""Tests for the SQL generator registration seam."""

from __future__ import annotations

import pytest

import core.seams.sql_generators as sql_generators
from core.seams.sql_generators import (
    attach_registered_sql_generators,
    clear_sql_generator_registrars,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def _reset_seam_state() -> None:
    clear_sql_generator_registrars()
    yield
    clear_sql_generator_registrars()


def test_attach_registered_sql_generators_uses_feature_loader(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        sql_generators,
        "load_feature_extensions",
        lambda: calls.append("load_feature_extensions"),
        raising=False,
    )
    monkeypatch.setattr(
        sql_generators,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(name)),
        raising=False,
    )

    attach_registered_sql_generators()

    assert calls == ["load_feature_extensions"]
