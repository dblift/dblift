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
        "dialect, prefix, predicate, suffix",
        [
            ("postgresql", "", "", " LIMIT 500"),
            ("mysql", "", "", " LIMIT 500"),
            ("sqlite", "", "", " LIMIT 500"),
            ("sqlserver", "TOP (500) ", "", ""),
            # Oracle without server_info can't prove the server is 12.1+, so
            # the version gate resolves to "unknown" and the render falls
            # back to the universally-valid ROWNUM predicate rather than the
            # declared (but possibly-invalid-here) FETCH FIRST form — see
            # TestVersionAwareRowLimit below.
            ("oracle", "", "ROWNUM <= 500", ""),
            ("db2", "", "", " FETCH FIRST 500 ROWS ONLY"),
        ],
    )
    def test_rendered_clauses(self, dialect: str, prefix: str, predicate: str, suffix: str) -> None:
        assert quirks(dialect).row_limit_clauses(500) == (prefix, predicate, suffix)

    def test_exactly_one_end_carries_the_cap(self) -> None:
        """A style that filled both ends would double-bound the query."""
        for dialect in ("postgresql", "mysql", "sqlite", "sqlserver", "oracle", "db2"):
            clauses = quirks(dialect).row_limit_clauses(10)
            populated = [f for f in clauses if f]
            assert len(populated) == 1, dialect

    def test_every_registered_dialect_produces_a_cap(self) -> None:
        """An uncapped query is the dangerous outcome, so no dialect may render nothing."""
        for dialect in all_registered_dialects():
            clauses = quirks(dialect).row_limit_clauses(10)
            assert "10" in "".join(clauses), f"{dialect} renders no row cap"

    def test_an_unknown_style_falls_back_to_limit(self) -> None:
        """Fail toward the majority form, never toward an unbounded query."""

        class _Odd(BaseQuirks):
            row_limit_style = "nonsense"

        assert _Odd(dialect_name="odd").row_limit_clauses(7) == ("", "", " LIMIT 7")

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


# --------------------------------------------------------------------------
# Version-aware resolution
# --------------------------------------------------------------------------


class TestVersionAwareRowLimit:
    """Oracle's row-limit form depends on the *server*, not just the dialect.

    ``FETCH FIRST n ROWS ONLY`` is Oracle 12.1+. python-oracledb's thin mode
    (the default) already requires 12.1, but thick mode reaches back to 11.2,
    so there is a real window where the declared form is invalid SQL.
    ``WHERE ROWNUM <= n`` is valid on *every* Oracle version, so it is what an
    unproven server gets — a gate that cannot be evaluated must not pick the
    narrower form.
    """

    def test_oracle_without_server_info_uses_the_universally_valid_form(self) -> None:
        clauses = quirks("oracle").row_limit_clauses(50)
        assert clauses.select_prefix == ""
        assert clauses.where_predicate == "ROWNUM <= 50"
        assert clauses.query_suffix == ""

    def test_oracle_on_a_proven_12c_server_uses_fetch_first(self) -> None:
        clauses = quirks("oracle").row_limit_clauses(50, server_info={"version": "12.1.0.2"})
        assert clauses.where_predicate == ""
        assert clauses.query_suffix == " FETCH FIRST 50 ROWS ONLY"

    def test_oracle_on_a_proven_11g_server_stays_on_rownum(self) -> None:
        clauses = quirks("oracle").row_limit_clauses(50, server_info={"version": "11.2.0.4"})
        assert clauses.where_predicate == "ROWNUM <= 50"
        assert clauses.query_suffix == ""

    def test_db2_fetch_first_is_not_version_gated(self) -> None:
        """Only Oracle carries the gate; DB2's FETCH FIRST predates any release we meet."""
        clauses = quirks("db2").row_limit_clauses(50)
        assert clauses.query_suffix == " FETCH FIRST 50 ROWS ONLY"
        assert clauses.where_predicate == ""

    def test_every_dialect_still_renders_exactly_one_cap(self) -> None:
        """Across all three fields, exactly one carries the bound."""
        for dialect in all_registered_dialects():
            c = quirks(dialect).row_limit_clauses(10)
            populated = [f for f in (c.select_prefix, c.where_predicate, c.query_suffix) if f]
            assert len(populated) == 1, f"{dialect} rendered {populated}"
            assert "10" in populated[0]


class TestVersionAwareJsonCast:
    """MySQL's JSON type — and therefore ``CAST(x AS JSON)`` — is 5.7.8+.

    Unlike the Oracle case, the declared form is valid on everything except an
    EOL release, so an unproven server keeps the cast. The gate only downgrades
    a server *proven* too old; it never changes the common path on a guess.
    """

    def test_mysql_without_server_info_keeps_the_cast(self) -> None:
        assert quirks("mysql").json_bind_cast(server_info=None) == "JSON"

    def test_mysql_on_a_proven_5_6_server_drops_the_cast(self) -> None:
        assert quirks("mysql").json_bind_cast(server_info={"version": "5.6.51"}) is None

    def test_mysql_on_a_proven_5_7_server_keeps_the_cast(self) -> None:
        assert quirks("mysql").json_bind_cast(server_info={"version": "5.7.44"}) == "JSON"

    def test_ungated_dialects_ignore_server_info(self) -> None:
        """PostgreSQL's JSONB long predates any server we can connect to."""
        assert quirks("postgresql").json_bind_cast(server_info={"version": "9.4"}) == "JSONB"

    def test_the_accessor_agrees_with_the_attribute_when_ungated(self) -> None:
        for dialect in all_registered_dialects():
            q = quirks(dialect)
            if dialect in {"mysql"}:
                continue
            assert q.json_bind_cast(server_info=None) == q.json_bind_cast_type, dialect
