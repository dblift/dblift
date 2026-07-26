"""Contract tests for the row-limit / upsert / JSON-cast capability quirks.

These three capabilities exist so callers stop branching on dialect names to
pick SQL syntax. Each one replaces a hand-maintained set of dialect strings in
the paid tiers (``{"oracle", "db2"}`` for ``FETCH FIRST``, ``{"mysql",
"mariadb"}`` for ``ON DUPLICATE KEY``, and so on).

The value of a capability is that it is *truthful* for every registered
dialect, including the ones nobody thought about when the original set was
written — the PostgreSQL-wire engines were missing from the JSON-cast set, so
a JSON restore against Citus or TimescaleDB emitted an uncast parameter and
the server rejected it. Inheriting the capability from ``PostgresqlQuirks``
fixes that class of omission by construction, which is what these tests pin.
"""

from __future__ import annotations

import pytest

from db.base_quirks import BaseQuirks
from db.plugins.mariadb.quirks import MariadbQuirks
from db.plugins.redshift.quirks import RedshiftQuirks
from db.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def _ensure_plugins_discovered() -> None:
    ProviderRegistry.discover_plugins()


def quirks(dialect: str) -> BaseQuirks:
    return ProviderRegistry.get_quirks(dialect)


def all_registered_dialects() -> "list[str]":
    """Every dialect key any plugin answers to, aliases included.

    Sweeping the aliases too is deliberate: ``get_quirks("mssql")`` and
    ``get_quirks("sqlserver")`` must agree, because a user may configure
    either and the capability has to hold for whichever they wrote.
    """
    return sorted({d for p in ProviderRegistry.list_plugins() for d in p.dialects})


# --------------------------------------------------------------------------
# row_limit_style
# --------------------------------------------------------------------------


class TestRowLimitStyle:
    @pytest.mark.parametrize(
        "dialect, expected",
        [
            ("postgresql", "limit"),
            ("mysql", "limit"),
            ("mariadb", "limit"),
            ("sqlite", "limit"),
            ("sqlserver", "top"),
            ("oracle", "fetch_first"),
            ("db2", "fetch_first"),
        ],
    )
    def test_declared_style(self, dialect: str, expected: str) -> None:
        assert quirks(dialect).row_limit_style == expected

    @pytest.mark.parametrize(
        "dialect, prefix, suffix",
        [
            ("postgresql", "", " LIMIT 500"),
            ("mysql", "", " LIMIT 500"),
            ("sqlite", "", " LIMIT 500"),
            ("sqlserver", "TOP (500) ", ""),
            ("oracle", "", " FETCH FIRST 500 ROWS ONLY"),
            ("db2", "", " FETCH FIRST 500 ROWS ONLY"),
        ],
    )
    def test_rendered_clauses(self, dialect: str, prefix: str, suffix: str) -> None:
        assert quirks(dialect).row_limit_clauses(500) == (prefix, suffix)

    def test_exactly_one_end_carries_the_cap(self) -> None:
        """A style that filled both ends would double-bound the query."""
        for dialect in ("postgresql", "mysql", "sqlite", "sqlserver", "oracle", "db2"):
            prefix, suffix = quirks(dialect).row_limit_clauses(10)
            assert bool(prefix) != bool(suffix), dialect

    def test_every_registered_dialect_produces_a_cap(self) -> None:
        """An uncapped query is the dangerous outcome, so no dialect may render nothing."""
        for dialect in all_registered_dialects():
            prefix, suffix = quirks(dialect).row_limit_clauses(10)
            assert "10" in (prefix + suffix), f"{dialect} renders no row cap"

    def test_an_unknown_style_falls_back_to_limit(self) -> None:
        """Fail toward the majority form, never toward an unbounded query."""

        class _Odd(BaseQuirks):
            row_limit_style = "nonsense"

        assert _Odd(dialect_name="odd").row_limit_clauses(7) == ("", " LIMIT 7")

    def test_row_limit_style_and_select_supports_limit_agree(self) -> None:
        """The two attributes overlap and nothing keeps them in sync.

        A dialect that can't append a bare trailing ``LIMIT``
        (``select_supports_limit = False``) is exactly a dialect that needs a
        non-default ``row_limit_style`` (``"top"`` or ``"fetch_first"``), and
        vice versa. This pins that the two flags are declared consistently
        for every registered dialect today (SQL Server/``"top"``,
        Oracle+DB2/``"fetch_first"``); it is not a structural guarantee, so a
        future dialect could still set one without the other.
        """
        for dialect in all_registered_dialects():
            q = quirks(dialect)
            non_default_style = q.row_limit_style != "limit"
            no_bare_limit = q.select_supports_limit is False
            assert non_default_style == no_bare_limit, dialect


# --------------------------------------------------------------------------
# upsert_style
# --------------------------------------------------------------------------


class TestUpsertStyle:
    @pytest.mark.parametrize(
        "dialect, expected",
        [
            ("postgresql", "on_conflict"),
            ("sqlite", "on_conflict"),
            ("mysql", "on_duplicate_key"),
            ("mariadb", "on_duplicate_key"),
            ("oracle", "none"),
            ("db2", "none"),
            ("sqlserver", "none"),
        ],
    )
    def test_declared_style(self, dialect: str, expected: str) -> None:
        assert quirks(dialect).upsert_style == expected

    def test_redshift_does_not_inherit_on_conflict(self) -> None:
        """Redshift subclasses PostgresqlQuirks but has no ON CONFLICT clause.

        Inheriting it would emit SQL the server rejects — the one case in this
        capability where the PostgreSQL family is not uniform.
        """
        assert quirks("redshift").upsert_style == "none"

    @pytest.mark.parametrize("dialect", ["citus", "timescaledb", "yugabytedb"])
    def test_pg_wire_engines_inherit_on_conflict(self, dialect: str) -> None:
        assert quirks(dialect).upsert_style == "on_conflict"

    def test_the_default_is_the_portable_fallback(self) -> None:
        """A dialect that declares nothing must not claim a syntax it lacks."""
        assert BaseQuirks(dialect_name="anything").upsert_style == "none"

    def test_every_dialect_declares_a_known_style(self) -> None:
        allowed = {"none", "on_conflict", "on_duplicate_key"}
        for dialect in all_registered_dialects():
            assert quirks(dialect).upsert_style in allowed, dialect


# --------------------------------------------------------------------------
# json_bind_cast_type
# --------------------------------------------------------------------------


class TestJsonBindCastType:
    @pytest.mark.parametrize(
        "dialect, expected",
        [
            ("postgresql", "JSONB"),
            ("cockroachdb", "JSONB"),
            ("mysql", "JSON"),
            ("sqlite", None),
            ("oracle", None),
            ("sqlserver", None),
            ("db2", None),
        ],
    )
    def test_declared_cast(self, dialect: str, expected: "str | None") -> None:
        assert quirks(dialect).json_bind_cast_type == expected

    def test_redshift_does_not_inherit_the_jsonb_cast(self) -> None:
        """Redshift has no JSONB type — semi-structured JSON is ``SUPER``.

        It subclasses ``PostgresqlQuirks`` and so would inherit ``"JSONB"``,
        but ``CAST(? AS JSONB)`` is rejected outright (*type "jsonb" does not
        exist*). This is the same reason Redshift overrides ``upsert_style``
        back to ``"none"``; the JSON cast needs the identical treatment.
        """
        assert quirks("redshift").json_bind_cast_type is None

    def test_mariadb_does_not_inherit_the_json_cast(self) -> None:
        """MariaDB does not implement ``CAST(expr AS JSON)`` (MDEV-26448).

        Its ``JSON`` type is an alias for ``LONGTEXT`` with a validity CHECK,
        so a serialized value binds as text with no cast at all. Inheriting
        MySQL's ``"JSON"`` emits SQL the MariaDB parser rejects.
        """
        assert quirks("mariadb").json_bind_cast_type is None

    @pytest.mark.parametrize("dialect", ["citus", "timescaledb", "yugabytedb"])
    def test_pg_wire_engines_inherit_the_cast(self, dialect: str) -> None:
        """The bug this capability closes.

        These engines were absent from the hand-maintained
        ``_JSONB_CAST_DIALECTS`` set, so a captured JSON value bound without a
        cast and the restore failed with "column is of type jsonb but
        expression is of type text". Inheritance makes the omission impossible.
        """
        assert quirks(dialect).json_bind_cast_type == "JSONB"

    def test_every_dialect_declares_a_known_cast_type(self) -> None:
        """The invariant, not the values: no dialect may claim a cast this
        project doesn't know how to render.

        Per-dialect tables like ``test_declared_cast`` above merely restate
        the implementation and would happily pass if a new dialect declared,
        say, ``"JSONB2"``. This sweeps every registered dialect and alias
        against the closed set of cast types dblift actually supports.
        """
        allowed = {None, "JSONB", "JSON"}
        for dialect in all_registered_dialects():
            assert quirks(dialect).json_bind_cast_type in allowed, dialect

    def test_redshift_and_mariadb_overrides_are_declared_on_the_subclass(self) -> None:
        """Pin the override *mechanism*, not just the value it resolves to.

        ``test_redshift_does_not_inherit_the_jsonb_cast`` and
        ``test_mariadb_does_not_inherit_the_json_cast`` above already fail if
        the override is deleted, because deletion falls through to the
        parent's ``"JSONB"``/``"JSON"``. This test checks the same fact a
        different way — that ``json_bind_cast_type`` is declared directly in
        each subclass's own body — so the guard does not depend on the
        parent chain continuing to resolve to a non-``None`` value forever.
        """
        assert "json_bind_cast_type" in vars(RedshiftQuirks)
        assert "json_bind_cast_type" in vars(MariadbQuirks)


# --------------------------------------------------------------------------
# update_subquery_requires_derived_table
# --------------------------------------------------------------------------


class TestUpdateSubqueryDerivedTable:
    @pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
    def test_mysql_family_requires_the_wrapper(self, dialect: str) -> None:
        """MySQL error 1093 rejects an UPDATE reading its own target table."""
        assert quirks(dialect).update_subquery_requires_derived_table is True

    @pytest.mark.parametrize(
        "dialect", ["postgresql", "sqlite", "oracle", "db2", "sqlserver", "citus"]
    )
    def test_everyone_else_takes_the_direct_form(self, dialect: str) -> None:
        """The wrapper is not free — it forces a materialisation."""
        assert quirks(dialect).update_subquery_requires_derived_table is False
