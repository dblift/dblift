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

from pathlib import Path

import pytest

from core import dialect_boundary
from core.dialect_boundary import ConnectionQuirks, DialectQuirks, ErrorQuirks
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

_REPO_ROOT = Path(__file__).resolve().parents[3]
_OSS_QUIRKS_SOURCES = (
    Path("db/base_quirks.py"),
    Path("db/plugins/cosmosdb/quirks.py"),
    Path("db/plugins/sqlite/quirks.py"),
)


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


@pytest.mark.parametrize("source_path", _OSS_QUIRKS_SOURCES)
def test_oss_quirks_do_not_type_depend_on_base_introspector(source_path: Path) -> None:
    source = (_REPO_ROOT / source_path).read_text(encoding="utf-8")
    assert "from core.introspection.base_introspector import BaseIntrospector" not in source
    assert "Type[BaseIntrospector]" not in source


def test_base_quirks_does_not_reference_rich_introspection_paths() -> None:
    source = (_REPO_ROOT / "db/base_quirks.py").read_text(encoding="utf-8")
    assert "core.introspection" not in source


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


@pytest.mark.parametrize("padded", [" ALWAYS", "ALWAYS ", " ALWAYS ", "ALWAYS\r\n", "\tALWAYS\n"])
def test_render_identity_clause_postgres_strips_surrounding_whitespace(padded: str) -> None:
    """A generation kind carrying padding must still render ALWAYS.

    The comparison is ``== "ALWAYS"`` and the fallback is *everything
    else*, so this method fails open: any value it does not recognise
    renders ``GENERATED BY DEFAULT AS IDENTITY``, which accepts
    caller-supplied values the ALWAYS column rejected. Padding is the
    cheapest way to trip that -- a ``CHAR(n)`` catalog column is
    blank-padded to its declared width -- and the failure is the exact
    silent relaxation the generation kind is captured to prevent, just
    reached by a different route. The method already upper-cases for the
    same reason: it cannot know who wrote the field, since ``from_dict``
    restores whatever a serialized snapshot carried.
    """

    class _Col:
        data_type = "integer"
        is_identity = True
        identity_seed = None
        identity_increment = None
        identity_generation = padded

    quirks = ProviderRegistry.get_quirks("postgresql")
    assert quirks.render_identity_clause(_Col()) == "GENERATED ALWAYS AS IDENTITY"


def test_render_identity_clause_postgres_blank_generation_stays_by_default() -> None:
    """Stripping must not turn "no information" into ALWAYS.

    A whitespace-only value says nothing about the column, and the
    no-information state renders ``BY DEFAULT``. This pins the fallback
    the strip is *not* allowed to move: only text that reads ALWAYS once
    trimmed may tighten the clause.
    """

    class _Col:
        data_type = "integer"
        is_identity = True
        identity_seed = None
        identity_increment = None
        identity_generation = "   "

    quirks = ProviderRegistry.get_quirks("postgresql")
    assert quirks.render_identity_clause(_Col()) == "GENERATED BY DEFAULT AS IDENTITY"


def test_render_identity_clause_postgres_emits_start_and_increment_when_both_set() -> None:
    """A live identity with seed=500 increment=5 must not re-render as 1/1.

    ``export-schema`` reads these attributes from the snapshot and the
    snapshot already holds the true values; dropping them here is how
    replay rebuilds ``START 1 INCREMENT 1`` while ``diff`` stays clean.
    """

    class _Col:
        data_type = "integer"
        is_identity = True
        identity_seed = 500
        identity_increment = 5
        identity_generation = "ALWAYS"

    quirks = ProviderRegistry.get_quirks("postgresql")
    clause = quirks.render_identity_clause(_Col())
    assert clause is not None
    assert "START WITH 500" in clause
    assert "INCREMENT BY 5" in clause
    assert clause == "GENERATED ALWAYS AS IDENTITY (START WITH 500 INCREMENT BY 5)"


@pytest.mark.parametrize(
    ("seed", "increment", "expected"),
    [
        (500, None, "GENERATED BY DEFAULT AS IDENTITY (START WITH 500 INCREMENT BY 1)"),
        (None, 5, "GENERATED BY DEFAULT AS IDENTITY (START WITH 1 INCREMENT BY 5)"),
    ],
)
def test_render_identity_clause_postgres_defaults_only_the_unset_sequence_option(
    seed: int | None, increment: int | None, expected: str
) -> None:
    """One recorded sequence option must still emit both START WITH and INCREMENT BY.

    The unset attribute defaults to 1, matching Oracle's identity renderer;
    the set attribute must keep its actual value.
    """

    class _Col:
        data_type = "integer"
        is_identity = True
        identity_seed = seed
        identity_increment = increment
        identity_generation = None

    quirks = ProviderRegistry.get_quirks("postgresql")
    assert quirks.render_identity_clause(_Col()) == expected


def test_render_identity_clause_postgres_omits_empty_sequence_options() -> None:
    """Neither seed nor increment recorded: bare identity keyword, no ``()``."""

    class _Col:
        data_type = "integer"
        is_identity = True
        identity_seed = None
        identity_increment = None
        identity_generation = "ALWAYS"

    quirks = ProviderRegistry.get_quirks("postgresql")
    clause = quirks.render_identity_clause(_Col())
    assert clause == "GENERATED ALWAYS AS IDENTITY"
    assert "(" not in clause
    assert ")" not in clause


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


def _nosql_plugin_names():
    ProviderRegistry.discover_plugins()
    return [
        plugin.name
        for plugin in ProviderRegistry.list_plugins()
        if getattr(ProviderRegistry.get_quirks(plugin.name), "is_nosql", False)
    ]


@pytest.mark.parametrize("plugin_name", _nosql_plugin_names())
def test_nosql_dialects_reject_sql_migrations(plugin_name):
    """Every document store must route .sql to DBLIFT-NOSQL-001 rather than
    to a translator — asserted by capability, so a new one is covered the
    day it registers."""
    quirks = ProviderRegistry.get_quirks(plugin_name)
    assert quirks.supports_sql_migrations is False
    assert quirks.is_nosql is True


def test_at_least_two_nosql_plugins_are_registered():
    """Guards the parametrization above against silently collecting nothing."""
    assert len(_nosql_plugin_names()) >= 2


@pytest.mark.parametrize(
    "dialect",
    [d for d in KNOWN_DIALECTS if d not in set(_nosql_plugin_names())],
)
def test_relational_dialects_accept_sql_migrations(dialect: str) -> None:
    """Every relational dialect keeps executing .sql migrations."""
    quirks = ProviderRegistry.get_quirks(dialect)
    assert (
        quirks.supports_sql_migrations is True
    ), f"{dialect}: supports_sql_migrations must stay True"


@pytest.mark.parametrize("dialect", KNOWN_DIALECTS)
def test_no_dialect_carries_sdk_translation_hooks(dialect: str) -> None:
    """The pseudo-SQL/SDK translation hooks are gone for good.

    They existed only to let CosmosDB smuggle SDK calls through generated
    SQL scripts. Nothing may reintroduce them.
    """
    quirks = ProviderRegistry.get_quirks(dialect)
    for hook in (
        "requires_sdk_for_drop",
        "sdk_operation_hint_prefix",
        "build_sdk_drop_operation",
        "generate_sdk_script",
    ):
        assert not hasattr(quirks, hook), f"{dialect}: {hook} must not come back"


def _registered_plugin_names():
    """Every registered dialect, not just ``KNOWN_DIALECTS``.

    The hook guarded below was answered by all twenty registered dialects —
    five declared a value and the rest inherited one — so the guard has to
    sweep all twenty. ``test_at_least_two_nosql_plugins_are_registered``
    already fails if this registry collects nothing.
    """
    return sorted(plugin.name for plugin in ProviderRegistry.list_plugins())


@pytest.mark.parametrize("dialect", _registered_plugin_names())
def test_no_dialect_declares_the_round_trip_object_type_hook(dialect: str) -> None:
    """``round_trip_extra_object_types`` belongs to the composition seam now.

    It was removed from :class:`BaseQuirks` and from the five plugin quirks
    classes that overrode it, because its contract was a list of object-type
    names walked by a driver that is not part of this distribution — nothing
    here could read it and check what those names meant.

    Two ways it comes back, and both are failures:

    * Re-declared on :class:`BaseQuirks` — every dialect answers again, and
      the seam has nothing left to contribute.
    * Left behind on a single plugin's quirks class — a *silent* dead
      override, since nothing in this repository reads it, right up until an
      installed package registers an extension supplying the hook for that
      dialect. ``core/seams/quirks.py`` refuses to compose an extension over
      a base class that already answers the hook, so the process then fails
      to start rather than mis-answering.

    Asserted against the pre-composition class from
    :meth:`ProviderRegistry.quirks_base_class`, never against
    :meth:`ProviderRegistry.get_quirks`: the composed class is exactly where
    a legitimately registered extension is *supposed* to put this hook, so
    reading it there would fail the installation this removal enables.
    """
    quirks_class = ProviderRegistry.quirks_base_class(dialect)
    assert not hasattr(quirks_class, "round_trip_extra_object_types"), (
        f"{dialect}: {quirks_class.__name__} declares or inherits "
        "round_trip_extra_object_types. Contribute it through "
        "core/seams/quirks.py instead — an extension cannot register for a "
        "dialect whose quirks class already answers the hook."
    )


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


# ---------------------------------------------------------------------------
# ADR-26 T0: ErrorQuirks + ConnectionQuirks sub-protocols.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Story 26-5: ``quote_qualified_folds_to_uppercase`` capability.
#
# ``DialectEnum.quote_qualified`` used to hardcode ``if key == "oracle"``.
# Oracle folds unquoted identifiers to uppercase at CREATE TABLE time, so the
# helper upper-cases the idents before quoting. DB2 shares Oracle's
# identifier-folding quirks but historically was NOT upper-cased here — the
# capability flag must be True for Oracle ONLY.
# ---------------------------------------------------------------------------


def test_oracle_quote_qualified_folds_to_uppercase() -> None:
    """Oracle is the only dialect that upper-cases in quote_qualified."""
    assert ProviderRegistry.get_quirks("oracle").quote_qualified_folds_to_uppercase is True


@pytest.mark.parametrize(
    "dialect",
    [d for d in KNOWN_DIALECTS if d != "oracle"],
)
def test_non_oracle_quote_qualified_does_not_fold_to_uppercase(dialect: str) -> None:
    """Every non-Oracle dialect (incl. DB2) leaves quote_qualified case untouched."""
    quirks = ProviderRegistry.get_quirks(dialect)
    assert quirks.quote_qualified_folds_to_uppercase is False, (
        f"{dialect}: quote_qualified_folds_to_uppercase must be False " f"(only Oracle upper-cases)"
    )


def test_base_quirks_quote_qualified_folds_to_uppercase_defaults_false() -> None:
    """The conservative default is False — unknown dialects do not fold."""
    assert BaseQuirks().quote_qualified_folds_to_uppercase is False


def test_base_quirks_satisfies_error_quirks_protocol() -> None:
    """T0: BaseQuirks must structurally satisfy the ErrorQuirks Protocol."""
    assert isinstance(BaseQuirks(), ErrorQuirks)


def test_base_quirks_satisfies_connection_quirks_protocol() -> None:
    """T0: BaseQuirks must structurally satisfy the ConnectionQuirks Protocol."""
    assert isinstance(BaseQuirks(), ConnectionQuirks)


def test_base_quirks_still_satisfies_aggregate_after_new_subprotocols() -> None:
    """T0: adding ErrorQuirks/ConnectionQuirks must not break the aggregate."""
    assert isinstance(BaseQuirks(), DialectQuirks)


def test_base_quirks_error_patterns_defaults_to_empty_list() -> None:
    """T0: the safe default for error_patterns() is an empty list."""
    assert BaseQuirks().error_patterns() == []


def test_base_quirks_engine_pool_options_defaults_to_empty_dict() -> None:
    """T0: the safe default for engine_pool_options() is an empty dict."""
    assert BaseQuirks().engine_pool_options() == {}


def test_new_subprotocols_are_exported() -> None:
    """T0: ErrorQuirks and ConnectionQuirks are part of the public surface."""
    assert "ErrorQuirks" in dialect_boundary.__all__
    assert "ConnectionQuirks" in dialect_boundary.__all__
