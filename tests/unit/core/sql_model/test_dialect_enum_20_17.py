"""Tests for the dialect quoting module functions (story 20-17 / 26-5).

Story 26-5 removed the ``DialectEnum`` canonical-name vocabulary (the 7
member literals were referenced only by tests). The surviving public
surface is the two module-level quoting functions; canonical-name
resolution now lives on ``ProviderRegistry.canonical_dialect_name``.
These tests pin the importability and resolution semantics.
"""

import pytest

from core.sql_model.dialect import quote_identifier, quote_qualified

pytestmark = [pytest.mark.unit]


class TestQuotingFunctionsImportable:
    """The quoting functions are importable from the package root."""

    def test_quote_identifier_importable_from_package(self):
        from core.sql_model import quote_identifier as qi

        assert qi("postgresql", "users") == '"users"'

    def test_quote_qualified_importable_from_package(self):
        from core.sql_model import quote_qualified as qq

        assert qq("postgresql", "public", "users") == '"public"."users"'

    def test_quoting_functions_in_all(self):
        import core.sql_model as mod

        assert "quote_identifier" in mod.__all__
        assert "quote_qualified" in mod.__all__

    def test_dialect_enum_removed(self):
        """The DialectEnum vocabulary is gone — package must not export it."""
        import core.sql_model as mod

        assert not hasattr(mod, "DialectEnum")
        assert "DialectEnum" not in mod.__all__


class TestCanonicalDialectNameResolution:
    """Canonical-name resolution replaces the old DialectEnum.from_string."""

    def test_case_insensitive_oracle(self):
        from db.provider_registry import ProviderRegistry

        assert ProviderRegistry.canonical_dialect_name("Oracle") == "oracle"

    def test_case_insensitive_postgresql(self):
        from db.provider_registry import ProviderRegistry

        assert ProviderRegistry.canonical_dialect_name("POSTGRESQL") == "postgresql"

    def test_unknown_dialect_returns_none(self):
        from db.provider_registry import ProviderRegistry

        assert ProviderRegistry.canonical_dialect_name("unknown_db") is None

    def test_empty_string_returns_none(self):
        from db.provider_registry import ProviderRegistry

        assert ProviderRegistry.canonical_dialect_name("") is None
