"""Tests for the SQL generator registration seam."""

from __future__ import annotations

import pytest

import dblift.core.seams.sql_generators as sql_generators
from dblift.core.seams.sql_generators import (
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


def test_empty_registrars_after_load_does_not_latch_bootstrapped(monkeypatch) -> None:
    """Same latch bug as AlterGeneratorFactory._ensure_populated and
    feature_loading.load_feature_extensions, one layer over PRO's own
    ``register_pro_features`` -> ``register_pro_generators`` direct call:
    ``_bootstrapped`` used to latch ``True`` unconditionally the first time
    this branch ran, even when ``load_feature_extensions()`` raced (a paid
    package's ``dblift.features`` entry point not yet visible) and left
    ``_registrars`` empty. A later call, even one where the entry point has
    since become visible, must still be allowed to retry -- not skip
    ``load_feature_extensions()`` forever because ``_bootstrapped`` was
    already (wrongly) set to ``True``.
    """
    monkeypatch.setattr(sql_generators, "load_feature_extensions", lambda: None, raising=False)

    attach_registered_sql_generators()

    assert sql_generators._bootstrapped is False, (
        "an empty _registrars result after load_feature_extensions() must not "
        "latch _bootstrapped, or a later call that WOULD populate _registrars "
        "never retries load_feature_extensions()"
    )


def test_a_later_call_with_a_registrar_available_succeeds_after_an_earlier_empty_call(
    monkeypatch,
) -> None:
    """Reproduces the race directly: first call's load_feature_extensions()
    finds nothing (as if the paid package's metadata resolved later), second
    call (as if register_sql_generator_registrar has since been called, the
    way register_pro_features calls it directly) must actually run the
    registrar -- not stay a no-op because the first call already latched
    ``_bootstrapped``.
    """
    monkeypatch.setattr(sql_generators, "load_feature_extensions", lambda: None, raising=False)
    attach_registered_sql_generators()
    assert sql_generators._bootstrapped is False

    calls: list[str] = []
    sql_generators.register_sql_generator_registrar(lambda: calls.append("ran"))
    attach_registered_sql_generators()

    assert calls == ["ran"]


def test_a_later_call_still_empty_retries_load_feature_extensions(monkeypatch) -> None:
    """Isolates the literal retry the fix's own comment describes, which the
    test above does not: that one's final assertion is satisfied by the
    unconditional ``for registrar in _registrars`` loop regardless of
    ``_bootstrapped``, and its second call never actually re-enters the
    ``if`` branch (``_registrars`` is already non-empty by then, which
    independently blocks re-entry). Here ``_registrars`` stays empty across
    BOTH calls, so the only way ``load_feature_extensions`` runs a second
    time is if ``_bootstrapped`` genuinely stayed ``False`` after the first,
    empty call.
    """
    calls: list[str] = []
    monkeypatch.setattr(
        sql_generators, "load_feature_extensions", lambda: calls.append("load"), raising=False
    )

    attach_registered_sql_generators()
    assert calls == ["load"]
    assert sql_generators._bootstrapped is False

    attach_registered_sql_generators()

    assert calls == ["load", "load"], (
        "with _registrars still empty after the first call, _bootstrapped must "
        "not have latched -- the second call must retry load_feature_extensions(), "
        "not skip it"
    )


def test_non_empty_registrars_after_load_still_latches_as_before(monkeypatch) -> None:
    """Regression guard: this fix only targets the empty-_registrars case,
    not every call -- a normal, successful bootstrap (load_feature_extensions
    populates _registrars, the common case for an installed paid tier) must
    still latch so a later call does not re-run load_feature_extensions on
    every single invocation."""
    calls: list[str] = []

    def _fake_load_feature_extensions():
        sql_generators.register_sql_generator_registrar(lambda: calls.append("ran"))

    monkeypatch.setattr(
        sql_generators,
        "load_feature_extensions",
        _fake_load_feature_extensions,
        raising=False,
    )

    attach_registered_sql_generators()
    assert sql_generators._bootstrapped is True
    assert calls == ["ran"]

    # A second call must NOT re-run load_feature_extensions -- the registrar
    # runs again (that part is unconditional, by design), but the loader
    # itself must not be invoked twice.
    calls.clear()
    load_calls: list[str] = []
    monkeypatch.setattr(
        sql_generators,
        "load_feature_extensions",
        lambda: load_calls.append("load"),
        raising=False,
    )
    attach_registered_sql_generators()
    assert load_calls == []
    assert calls == ["ran"]
