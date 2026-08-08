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
        """The two attributes overlap, but the overlap is not total -- db2 is
        a confirmed exception, not a structural guarantee.

        A dialect with a non-default ``row_limit_style`` (``"top"`` or
        ``"fetch_first"``) usually can't append a bare trailing ``LIMIT``
        either, and this pins that correlation for every dialect except the
        one now known not to hold it. SQL Server and Oracle still fit: both
        set a non-default style AND ``select_supports_limit = False``.

        DB2 breaks the pattern: it declares ``row_limit_style =
        "fetch_first"`` as its PREFERRED rendering (matching Oracle's
        convention of declaring its native/canonical form), but a live db2
        12.01.0500 server, probed via
        tests/integration/capabilities/test_engine_capabilities.py
        ::test_row_limit_clauses_match_the_engine (CI run 30346957093,
        cmodiano/dblift), accepted a bare trailing ``LIMIT`` too --
        contradicting the ``select_supports_limit = False`` this dialect
        used to declare. The two questions are genuinely different
        ("what do I render" vs. "may an optional probe append a bare LIMIT
        at all") and db2 is the first registered dialect where they
        diverge. Not a structural guarantee before this, and still not one
        now: a future dialect could align with either db2's shape or the
        SQL-Server/Oracle shape.
        """
        # ``ibm_db_sa`` is db2's own alias (see ``all_registered_dialects``'s
        # docstring: aliases are swept deliberately and must agree with the
        # dialect they alias) -- it resolves to the same Db2Quirks instance,
        # so it diverges for the identical reason db2 does.
        DIVERGES_FROM_THE_USUAL_CORRELATION = {"db2", "ibm_db_sa"}
        for dialect in all_registered_dialects():
            q = quirks(dialect)
            non_default_style = q.row_limit_style != "limit"
            no_bare_limit = q.select_supports_limit is False
            if dialect in DIVERGES_FROM_THE_USUAL_CORRELATION:
                assert non_default_style and not no_bare_limit, dialect
                continue
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
# supports_concurrent_index
# --------------------------------------------------------------------------


class TestSupportsConcurrentIndex:
    """The bug this capability closes.

    ``supports_concurrent_index`` defaults to ``False`` on ``BaseQuirks`` and
    was declared ``True`` only by ``PostgresqlQuirks`` — every PostgreSQL-wire
    engine inherited that ``True`` with nobody having checked whether
    ``CREATE INDEX CONCURRENTLY`` means the same thing for them. It does not:
    Redshift has no ``CREATE INDEX`` at all, CockroachDB and YugabyteDB build
    every index online regardless of the keyword (so recommending it implies
    the plain form blocks, backwards), and TimescaleDB's own docs say
    ``CONCURRENTLY`` is not supported directly on a hypertable at all.
    """

    @pytest.mark.parametrize(
        "dialect, expected",
        [
            ("postgresql", True),
            ("citus", True),  # verified against Citus's own DDL reference: works per-shard
            ("redshift", False),
            ("cockroachdb", False),
            ("timescaledb", False),
            ("yugabytedb", False),
            ("mysql", False),
            ("mariadb", False),
            ("sqlite", False),
            ("oracle", False),
            ("sqlserver", False),
            ("db2", False),
        ],
    )
    def test_declared_value(self, dialect: str, expected: bool) -> None:
        assert quirks(dialect).supports_concurrent_index is expected

    def test_redshift_has_no_create_index_syntax_at_all(self) -> None:
        """Redshift uses sort keys and zone maps instead of B-tree indexes.

        It subclasses ``PostgresqlQuirks`` and so would inherit ``True``, but
        there is no ``CREATE INDEX`` of any form to add ``CONCURRENTLY`` to.
        """
        assert quirks("redshift").supports_concurrent_index is False

    def test_cockroachdb_builds_every_index_online_regardless(self) -> None:
        """Per Cockroach Labs' CREATE INDEX reference: ``CONCURRENTLY`` is
        "optional, no-op syntax for PostgreSQL compatibility. All indexes are
        created concurrently in CockroachDB." Recommending the keyword implies
        the plain form blocks, which is never true here.
        """
        assert quirks("cockroachdb").supports_concurrent_index is False

    def test_yugabytedb_defaults_to_concurrent_already(self) -> None:
        """Per YugabyteDB's own CREATE INDEX reference: "the default mode is
        CONCURRENTLY, wherever possible" — online index backfill is already
        the default, and ``NONCONCURRENTLY`` is the actual opt-out. Inheriting
        PostgreSQL's ``True`` has it backwards.
        """
        assert quirks("yugabytedb").supports_concurrent_index is False

    def test_timescaledb_does_not_support_concurrently_on_hypertables(self) -> None:
        """TimescaleDB's own docs: not supported directly on a hypertable; the
        documented alternative is ``WITH (timescaledb.transaction_per_chunk)``,
        a different clause entirely, not ``CONCURRENTLY``.
        """
        assert quirks("timescaledb").supports_concurrent_index is False

    def test_citus_inherits_true_because_it_actually_works_per_shard(self) -> None:
        """Verified against Citus's own DDL reference before leaving this
        inherited rather than overridden: ``CREATE INDEX CONCURRENTLY`` is
        Citus's own documented, recommended way to add an index to a
        distributed table without blocking writes, propagated per shard.
        This is the one PostgreSQL-wire engine in this sweep where the
        inherited ``True`` is correct, not an unchecked assumption.
        """
        assert quirks("citus").supports_concurrent_index is True

    @pytest.mark.parametrize("dialect", ["neon", "supabase", "aurora-postgresql", "alloydb"])
    def test_true_postgres_clones_inherit_true(self, dialect: str) -> None:
        """Neon, Supabase, Aurora PostgreSQL, and AlloyDB are managed PostgreSQL
        itself, not a different storage/execution engine the way Citus,
        CockroachDB, TimescaleDB, and YugabyteDB are — confirmed for Neon
        against its own docs (``CREATE INDEX CONCURRENTLY`` works, the one
        documented caveat is routing: it needs a direct connection, not a
        pooled one, which is a connection-layer concern this flag doesn't
        model). Pinned explicitly rather than left to bare inheritance, so a
        future audit of "every PostgreSQL-wire engine" has something to run
        against instead of re-deriving the list from ``all_registered_dialects()``.
        """
        assert quirks(dialect).supports_concurrent_index is True

    def test_overrides_are_declared_on_the_quirks_class(self) -> None:
        """Pin the override *mechanism*, not just the resolved value.

        The per-dialect tests above already fail if an override is deleted
        (it would fall through to PostgreSQL's inherited ``True``), but this
        checks the same fact a different way: the flag is a real class
        attribute on each dialect's own quirks class, whether declared
        directly (``RedshiftQuirks``, ``CockroachdbQuirks``) or injected via
        ``quirks_overrides`` into the ``make_pg_compatible_quirks``-built
        class (``TimescaledbQuirks``, ``YugabytedbQuirks``) — so the guard
        does not depend on the parent chain continuing to resolve to
        ``True`` forever.
        """
        from db.plugins._pg_compatible import TimescaledbQuirks, YugabytedbQuirks
        from db.plugins.cockroachdb.quirks import CockroachdbQuirks

        assert "supports_concurrent_index" in vars(RedshiftQuirks)
        assert "supports_concurrent_index" in vars(CockroachdbQuirks)
        assert "supports_concurrent_index" in vars(TimescaledbQuirks)
        assert "supports_concurrent_index" in vars(YugabytedbQuirks)


# --------------------------------------------------------------------------
# update_subquery_requires_derived_table
# --------------------------------------------------------------------------


class TestUpdateSubqueryDerivedTable:
    def test_mysql_requires_the_wrapper(self) -> None:
        """MySQL error 1093 rejects an UPDATE reading its own target table."""
        assert quirks("mysql").update_subquery_requires_derived_table is True

    def test_mariadb_takes_the_direct_form(self) -> None:
        """MariaDB accepts the self-referencing form without a derived-table wrap."""
        assert quirks("mariadb").update_subquery_requires_derived_table is False

    @pytest.mark.parametrize(
        "dialect", ["postgresql", "sqlite", "oracle", "db2", "sqlserver", "citus"]
    )
    def test_everyone_else_takes_the_direct_form(self, dialect: str) -> None:
        assert quirks(dialect).update_subquery_requires_derived_table is False


# --------------------------------------------------------------------------
# subquery_row_limit_requires_derived_table
# --------------------------------------------------------------------------


class TestSubqueryRowLimitRequiresDerivedTable:
    """Orthogonal to :attr:`update_subquery_requires_derived_table` above.

    MariaDB's ``False`` there is correct (error 1093 does not apply) and
    stays correct here too — this flag is about a DIFFERENT error (1235:
    "doesn't yet support 'LIMIT & IN/ALL/ANY/SOME subquery'"), which MySQL
    and MariaDB both raise for the identical shape
    (``... WHERE pk IN (SELECT pk FROM t ... LIMIT n)``) regardless of
    whether the subquery also references its own target table.
    """

    def test_mysql_requires_the_wrapper(self) -> None:
        assert quirks("mysql").subquery_row_limit_requires_derived_table is True

    def test_mariadb_inherits_the_wrapper_from_mysql(self) -> None:
        """Not overridden back to False the way update_subquery_requires_
        derived_table is — MariaDB genuinely hits error 1235 too.
        """
        assert quirks("mariadb").subquery_row_limit_requires_derived_table is True

    @pytest.mark.parametrize(
        "dialect", ["postgresql", "sqlite", "oracle", "db2", "sqlserver", "citus"]
    )
    def test_no_other_dialect_wraps(self, dialect: str) -> None:
        assert quirks(dialect).subquery_row_limit_requires_derived_table is False


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


# --------------------------------------------------------------------------
# Composition safety
# --------------------------------------------------------------------------


class TestComposeWhere:
    """The caller must not have to reimplement WHERE/AND glue.

    The first draft documented the glue as an f-string for each call site to
    copy. Executed against a dialect with no ``where_predicate`` and a caller
    with no predicate of its own, that example rendered
    ``SELECT cols FROM t WHERE  LIMIT 10`` — a dangling WHERE. A reference
    implementation that is itself wrong is evidence the shape is error-prone,
    so the glue moves into the type that owns the fragments.
    """

    def test_no_predicate_on_either_side_yields_nothing(self) -> None:
        assert quirks("postgresql").row_limit_clauses(10).compose_where("") == ""

    def test_callers_predicate_alone(self) -> None:
        assert quirks("postgresql").row_limit_clauses(10).compose_where("id > 5") == (
            " WHERE id > 5"
        )

    def test_row_cap_predicate_alone(self) -> None:
        assert quirks("oracle").row_limit_clauses(10).compose_where("") == " WHERE ROWNUM <= 10"

    def test_both_are_anded(self) -> None:
        """The caller's predicate is parenthesised before the AND.

        This test originally asserted the unparenthesised ``id > 5 AND ROWNUM
        <= 10``, which is correct for *this* predicate and wrong in general —
        it pinned the precedence bug rather than the behaviour. See
        ``TestComposeWhereGuardsPrecedence`` for the case that exposed it.
        """
        assert quirks("oracle").row_limit_clauses(10).compose_where("id > 5") == (
            " WHERE (id > 5) AND ROWNUM <= 10"
        )

    def test_a_blank_predicate_is_treated_as_absent(self) -> None:
        assert quirks("oracle").row_limit_clauses(10).compose_where("   ") == (
            " WHERE ROWNUM <= 10"
        )

    def test_the_documented_composition_is_valid_for_every_dialect(self) -> None:
        """Render the documented pattern for all dialects and reject broken SQL."""
        for dialect in all_registered_dialects():
            c = quirks(dialect).row_limit_clauses(10)
            sql = f"SELECT {c.select_prefix}col FROM t{c.compose_where('')}{c.query_suffix}"
            assert "WHERE  " not in sql, f"{dialect}: dangling WHERE in {sql!r}"
            assert not sql.rstrip().endswith("WHERE"), f"{dialect}: {sql!r}"


class TestOrderedTopNIsRefusedWhereItWouldLie:
    """ROWNUM is applied *before* ORDER BY — it cannot express an ordered top-N.

    ``SELECT ... WHERE ROWNUM <= n ORDER BY val`` takes n rows in whatever
    order the access path produced and *then* sorts them, so it does not
    return the true top-n by ``val``. The correct pre-12.1 form nests the
    ordered query in a subquery, which this three-fragment shape cannot
    express. Rather than silently return wrong rows, the call is refused.
    """

    def test_oracle_refuses_an_ordered_cap_when_the_version_is_unproven(self) -> None:
        with pytest.raises(ValueError, match="ORDER BY"):
            quirks("oracle").row_limit_clauses(10, ordered=True)

    def test_oracle_refuses_an_ordered_cap_on_a_proven_11g_server(self) -> None:
        with pytest.raises(ValueError, match="ORDER BY"):
            quirks("oracle").row_limit_clauses(
                10, ordered=True, server_info={"version": "11.2.0.4"}
            )

    def test_oracle_allows_an_ordered_cap_on_a_proven_12c_server(self) -> None:
        c = quirks("oracle").row_limit_clauses(10, ordered=True, server_info={"version": "19.3"})
        assert c.query_suffix == " FETCH FIRST 10 ROWS ONLY"

    @pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite", "sqlserver", "db2"])
    def test_other_dialects_are_unaffected_by_ordered(self, dialect: str) -> None:
        """Only the rownum form has the semantic gap; nothing else is restricted."""
        assert quirks(dialect).row_limit_clauses(10, ordered=True) == quirks(
            dialect
        ).row_limit_clauses(10, ordered=False)

    def test_unordered_is_the_default_and_still_yields_rownum(self) -> None:
        assert quirks("oracle").row_limit_clauses(10).where_predicate == "ROWNUM <= 10"


class TestComposeWhereGuardsPrecedence:
    """``AND`` binds tighter than ``OR``, so the caller's predicate needs parens.

    Gluing a top-level ``OR`` predicate to the row cap unparenthesised reads as
    ``a OR (b AND ROWNUM <= n)`` — the first branch escapes the cap entirely and
    the query is *unbounded*, not merely mis-ordered. That is the exact class of
    error this helper exists to take away from callers, so it cannot be left to
    a docstring warning.
    """

    def test_a_top_level_or_predicate_stays_bounded(self) -> None:
        clauses = quirks("oracle").row_limit_clauses(10)
        composed = clauses.compose_where("a = 1 OR b = 2")
        assert composed == " WHERE (a = 1 OR b = 2) AND ROWNUM <= 10"

    def test_a_simple_predicate_is_also_parenthesised_for_consistency(self) -> None:
        """One rendering rule beats a heuristic that inspects the predicate."""
        clauses = quirks("oracle").row_limit_clauses(10)
        assert clauses.compose_where("id > 5") == " WHERE (id > 5) AND ROWNUM <= 10"

    def test_a_lone_caller_predicate_is_not_parenthesised(self) -> None:
        """Nothing is being ANDed to it, so parens would be noise."""
        assert quirks("postgresql").row_limit_clauses(10).compose_where("a = 1 OR b = 2") == (
            " WHERE a = 1 OR b = 2"
        )

    def test_none_is_treated_as_no_predicate(self) -> None:
        """Callers reach for ``None`` when threading an optional predicate."""
        assert quirks("oracle").row_limit_clauses(10).compose_where(None) == (" WHERE ROWNUM <= 10")
        assert quirks("postgresql").row_limit_clauses(10).compose_where(None) == ""
