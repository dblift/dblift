"""Reference-dialect capability and registry lookup.

Pin the default False capability, PostgreSQL's True override and the
single-winner ``ProviderRegistry.reference_dialect_name()`` lookup.
"""

import pytest

from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_registry import ProviderRegistry


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
