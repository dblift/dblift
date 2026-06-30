"""ADR-26 E: undo-script generators resolve the sqlglot read-dialect
through a shared registry-backed helper instead of hardcoding ``"postgres"``.
"""

from core.migration.scripting.undo_script_generator._helpers import (
    resolve_sqlglot_read_dialect,
)
from db.provider_registry import ProviderRegistry


def test_known_dialect_uses_its_own_sqlglot_dialect():
    assert resolve_sqlglot_read_dialect("oracle") == "oracle"
    assert resolve_sqlglot_read_dialect("sqlserver") == "tsql"
    assert resolve_sqlglot_read_dialect("mysql") == "mysql"


def test_empty_or_unknown_dialect_falls_back_to_registry_postgres():
    # The fallback is the PostgreSQL plugin's sqlglot dialect, derived from
    # the registry (not a hardcoded literal in framework code).
    expected = ProviderRegistry.get_quirks(
        ProviderRegistry.canonical_dialect_name("postgres") or ""
    ).sqlglot_dialect
    assert resolve_sqlglot_read_dialect("") == expected
    assert resolve_sqlglot_read_dialect("totally-unknown") == expected
    # Behaviour parity with the previous hardcoded fallback.
    assert resolve_sqlglot_read_dialect("") == "postgres"
