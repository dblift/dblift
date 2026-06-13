"""Conformance tests for the Epic 26/27 ``DialectQuirks`` boundary.

Every registered plugin must:

1. Resolve to a :class:`BaseQuirks` instance through ``ProviderRegistry.get_quirks``.
2. Carry a non-empty ``dialect_name`` matching the registered dialect.
3. Satisfy the structural :class:`DialectQuirks` Protocol at runtime.

These tests are the contract guard for stories 26-3..26-11. As those
stories add hooks to the protocol, this file gains assertions for the
new defaults.
"""

from __future__ import annotations

import pytest

from core.dialect_boundary import DialectQuirks
from db.base_quirks import BaseQuirks
from db.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def _ensure_plugins_discovered() -> None:
    ProviderRegistry.discover_plugins()


KNOWN_DIALECTS = (
    "postgresql",
    "mysql",
    "mariadb",
    "oracle",
    "sqlserver",
    "db2",
    "sqlite",
    "cosmosdb",
)

# Aliases registered alongside the canonical names. Each must round-trip
# through ``get_quirks(<alias>)`` with ``dialect_name == <alias>`` so the
# invariant ``provider.config.database.type == provider.quirks.dialect_name``
# holds for callers that configure their database with the alias form.
# Bugbot finding on PR #240 commit 372791f9.
#
# Note: ``mariadb`` is no longer an alias — it has its own first-party
# plugin (Epic 26 story 26-13). It now appears in ``KNOWN_DIALECTS``.
KNOWN_ALIASES = ("postgres", "mssql", "sqlite3")


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_get_quirks_returns_base_subclass(dialect: str) -> None:
    quirks = ProviderRegistry.get_quirks(dialect)
    assert isinstance(quirks, BaseQuirks), (
        f"{dialect}: get_quirks() must return a BaseQuirks subclass; "
        f"got {type(quirks).__name__}"
    )


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_quirks_dialect_name_matches_registration(dialect: str) -> None:
    quirks = ProviderRegistry.get_quirks(dialect)
    assert (
        quirks.dialect_name == dialect
    ), f"{dialect}: quirks.dialect_name == {quirks.dialect_name!r}, expected {dialect!r}"


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_quirks_satisfies_dialect_quirks_protocol(dialect: str) -> None:
    quirks = ProviderRegistry.get_quirks(dialect)
    assert isinstance(
        quirks, DialectQuirks
    ), f"{dialect}: quirks instance does not satisfy DialectQuirks runtime Protocol"


@pytest.mark.parametrize("alias", KNOWN_ALIASES)
def test_alias_preserves_dialect_name(alias: str) -> None:
    """Aliases (postgres/mariadb/mssql/sqlite3) round-trip with their own name.

    Regression guard for the Bugbot-flagged invariant: the quirks
    instance returned by ``get_quirks("postgres")`` must report
    ``dialect_name == "postgres"``, not ``"postgresql"``. Otherwise
    ``provider.config.database.type`` and ``provider.quirks.dialect_name``
    drift apart and any code using ``dialect_name`` for logging or
    error messages reports the wrong identifier.
    """
    quirks = ProviderRegistry.get_quirks(alias)
    assert (
        quirks.dialect_name == alias
    ), f"alias {alias!r}: quirks.dialect_name == {quirks.dialect_name!r}, expected {alias!r}"


def test_unknown_dialect_falls_back_to_base_quirks() -> None:
    quirks = ProviderRegistry.get_quirks("nonexistent-db")
    assert type(quirks) is BaseQuirks
    assert quirks.dialect_name == "nonexistent-db"


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_normalize_column_data_type_returns_string(dialect: str) -> None:
    """Story 27-1: normalize_column_data_type must return a str for any dialect."""

    class _FakeCol:
        data_type = "VARCHAR(255)"
        is_identity = False

    quirks = ProviderRegistry.get_quirks(dialect)
    result = quirks.normalize_column_data_type(_FakeCol(), "VARCHAR(255)")
    assert isinstance(
        result, str
    ), f"{dialect}: normalize_column_data_type must return str, got {type(result)}"
    assert result  # non-empty


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_render_identity_clause_returns_str_or_none(dialect: str) -> None:
    """Story 27-2: render_identity_clause must return Optional[str]."""

    class _FakeCol:
        data_type = "integer"
        is_identity = True
        identity_seed = 1
        identity_increment = 1
        identity_generation = None

    quirks = ProviderRegistry.get_quirks(dialect)
    result = quirks.render_identity_clause(_FakeCol())
    assert result is None or isinstance(
        result, str
    ), f"{dialect}: render_identity_clause must return str or None, got {type(result)}"


def test_render_identity_clause_postgres_serial_returns_none() -> None:
    """Story 27-2: PostgreSQL serial types must not emit an extra GENERATED clause."""

    class _SerialCol:
        data_type = "bigserial"
        is_identity = True
        identity_seed = None
        identity_increment = None
        identity_generation = None

    quirks = ProviderRegistry.get_quirks("postgresql")
    assert quirks.render_identity_clause(_SerialCol()) is None


def test_render_identity_clause_mysql_returns_auto_increment() -> None:
    """Story 27-2: MySQL identity must emit AUTO_INCREMENT."""

    class _Col:
        data_type = "int"
        is_identity = True

    quirks = ProviderRegistry.get_quirks("mysql")
    assert quirks.render_identity_clause(_Col()) == "AUTO_INCREMENT"


def test_fk_reference_bind_params_oracle_has_four_items() -> None:
    """Story 27-4: Oracle FK bind list must include schema twice."""
    quirks = ProviderRegistry.get_quirks("oracle")
    params = quirks.fk_reference_bind_params("MY_SCHEMA", "MY_TABLE", "MY_COL")
    assert params == ["MY_SCHEMA", "MY_SCHEMA", "MY_TABLE", "MY_COL"]


@pytest.mark.parametrize(
    "dialect",
    [d for d in KNOWN_DIALECTS if d != "oracle"],
)
def test_fk_reference_bind_params_non_oracle_has_three_items(dialect: str) -> None:
    """Story 27-4: Non-Oracle FK bind list must have three items."""
    quirks = ProviderRegistry.get_quirks(dialect)
    params = quirks.fk_reference_bind_params("s", "t", "c")
    assert params == ["s", "t", "c"], f"{dialect}: fk_reference_bind_params returned {params!r}"


def test_cosmosdb_requires_sdk_for_drop() -> None:
    """Story 27-3: CosmosDB must declare SDK-required drops."""
    quirks = ProviderRegistry.get_quirks("cosmosdb")
    assert quirks.requires_sdk_for_drop() is True


@pytest.mark.parametrize(
    "dialect",
    [d for d in KNOWN_DIALECTS if d != "cosmosdb"],
)
def test_non_cosmosdb_does_not_require_sdk_for_drop(dialect: str) -> None:
    """Story 27-3: Non-CosmosDB dialects must not require SDK drops."""
    quirks = ProviderRegistry.get_quirks(dialect)
    assert (
        quirks.requires_sdk_for_drop() is False
    ), f"{dialect}: requires_sdk_for_drop() must return False"


def test_unwrap_default_value_sqlserver_strips_parens() -> None:
    """Story 27-5: SQL Server must strip outer parens from simple defaults."""

    class _Col:
        data_type = "int"

    quirks = ProviderRegistry.get_quirks("sqlserver")
    assert quirks.unwrap_default_value("(42)", _Col()) == "42"
    assert quirks.unwrap_default_value("(a + b)", _Col()) == "(a + b)"


def test_unwrap_default_value_mysql_normalises_string_default() -> None:
    """Story 27-5: MySQL must normalise backtick-quoted string defaults to single quotes."""

    class _Col:
        data_type = "VARCHAR"

    quirks = ProviderRegistry.get_quirks("mysql")
    assert quirks.unwrap_default_value("`hello`", _Col()) == "'hello'"


def test_each_first_party_plugin_declares_quirks_class() -> None:
    """Every first-party plugin in this repo ships ``quirks.py`` (story 26-2).

    Third-party plugins may omit it — they get :class:`BaseQuirks` —
    but in-tree plugins are the test bed for the epic and must opt
    in so subsequent stories have somewhere to add overrides.
    """
    missing = []
    for dialect in KNOWN_DIALECTS:
        plugin_info = ProviderRegistry._plugins.get(dialect)
        assert plugin_info is not None, f"{dialect} plugin not registered"
        if plugin_info.quirks_class is None:
            missing.append(dialect)
    assert not missing, (
        "First-party plugins missing quirks.py: "
        + ", ".join(missing)
        + ". See docs/architecture/EPIC-26-dialect-plugin-isolation.md story 26-2."
    )
