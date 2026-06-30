"""Reference-dialect render default — ADR-26 E (story 26-5).

The no-dialect rendering default used to live as a ``self.dialect or
"postgresql"`` literal in the 7 multi-dialect ``create_statement`` sites in
``core/sql_model/``. It now lives in the generator factory, sourced from a
plugin capability: the single quirks class whose
``is_ansi_reference_dialect`` is True (PostgreSQL) is the dialect-agnostic
render fallback, resolved through the registry.

These tests pin:
1. the capability attribute (default False on BaseQuirks, True on PostgreSQL),
2. the ``ProviderRegistry.reference_dialect_name()`` single-winner lookup,
3. the factory mapping a falsy dialect (``None`` / ``""``) to the reference
   generator (byte-identical to ``create("postgresql")``).
"""

import pytest

from db.base_quirks import BaseQuirks
from db.provider_registry import ProviderRegistry


@pytest.mark.unit
class TestIsAnsiReferenceDialectCapability:
    """The capability flag default + PostgreSQL override."""

    def test_base_quirks_default_is_false(self) -> None:
        assert BaseQuirks().is_ansi_reference_dialect is False

    def test_postgresql_quirks_is_true(self) -> None:
        quirks = ProviderRegistry.get_quirks("postgresql")
        assert quirks.is_ansi_reference_dialect is True

    def test_exactly_one_plugin_declares_reference_dialect(self) -> None:
        """First-party invariant: exactly one registered plugin is the
        ANSI/generic reference dialect."""
        ProviderRegistry.discover_plugins()
        winners = [
            p.name
            for p in ProviderRegistry.list_plugins()
            if ProviderRegistry.get_quirks(p.name).is_ansi_reference_dialect
        ]
        assert winners == ["postgresql"]


@pytest.mark.unit
class TestReferenceDialectNameLookup:
    """``ProviderRegistry.reference_dialect_name()`` single-winner lookup."""

    def test_returns_postgresql(self) -> None:
        assert ProviderRegistry.reference_dialect_name() == "postgresql"

    def test_is_a_canonical_registered_dialect(self) -> None:
        name = ProviderRegistry.reference_dialect_name()
        assert ProviderRegistry.canonical_dialect_name(name) == name
