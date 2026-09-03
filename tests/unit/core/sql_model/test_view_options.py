"""Unit tests for ``dblift.core.sql_model.view_options.ViewOptions`` and the
``View.from_options`` / ``View.to_options`` classmethods (SIMP-48).

Mirrors ``test_table_options.py``: instances built via ``from_options``
must be indistinguishable from instances built via the legacy 20-kwarg
constructor, and ``to_options`` must round-trip back to a structurally
equal ``ViewOptions``.
"""

from __future__ import annotations

import dataclasses

import pytest

from dblift.core.sql_model.view import View
from dblift.core.sql_model.view_options import (
    MaterializedViewOptions,
    MySqlViewOptions,
    OracleViewOptions,
    PostgresViewOptions,
    ViewOptions,
)

# ---------------------------------------------------------------------------
# Dataclass immutability and defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestViewOptionsImmutability:
    def test_empty_options_has_default_subgroups(self):
        opts = ViewOptions()
        assert isinstance(opts.materialized_view, MaterializedViewOptions)
        assert isinstance(opts.postgres, PostgresViewOptions)
        assert isinstance(opts.mysql, MySqlViewOptions)
        assert isinstance(opts.oracle, OracleViewOptions)
        assert opts.dependencies == []

    def test_options_are_frozen(self):
        opts = ViewOptions()
        with pytest.raises(dataclasses.FrozenInstanceError):
            opts.dependencies = ["x"]  # type: ignore[misc]

    def test_subgroups_are_frozen(self):
        ms = MySqlViewOptions(algorithm="MERGE")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ms.algorithm = "TEMPTABLE"  # type: ignore[misc]

    def test_to_kwargs_returns_legacy_shape(self):
        opts = ViewOptions(
            materialized_view=MaterializedViewOptions(refresh_method="FAST"),
            postgres=PostgresViewOptions(unlogged=True, security_definer=True),
            mysql=MySqlViewOptions(algorithm="MERGE", sql_security="DEFINER"),
            oracle=OracleViewOptions(force=True),
            dependencies=["other_view"],
        )
        kwargs = opts.to_kwargs()

        assert kwargs["refresh_method"] == "FAST"
        assert kwargs["unlogged"] is True
        assert kwargs["security_definer"] is True
        assert kwargs["algorithm"] == "MERGE"
        assert kwargs["sql_security"] == "DEFINER"
        assert kwargs["force"] is True
        assert kwargs["dependencies"] == ["other_view"]
        # Defaults pass through unchanged
        assert kwargs["definer"] is None
        assert kwargs["last_refresh"] is None


# ---------------------------------------------------------------------------
# View.from_options equivalence with legacy constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFromOptionsEquivalence:
    def test_minimal_construction(self):
        legacy = View(name="v", query="SELECT 1", dialect="postgresql")
        typed = View.from_options(
            "v", query="SELECT 1", dialect="postgresql", options=ViewOptions()
        )

        assert typed.name == legacy.name
        assert typed.query == legacy.query
        assert typed.dialect == legacy.dialect
        assert typed.unlogged is None
        assert typed.algorithm is None
        assert typed.dependencies == []

    def test_materialized_options_propagate(self):
        opts = ViewOptions(
            materialized_view=MaterializedViewOptions(
                is_populated=True,
                refresh_method="FAST",
                refresh_mode="ON DEMAND",
                fast_refreshable=True,
                last_refresh="2025-01-01",
            )
        )
        v = View.from_options(
            "v", query="SELECT 1", materialized=True, options=opts, dialect="oracle"
        )

        assert v.materialized is True
        assert v.is_populated is True
        assert v.refresh_method == "FAST"
        assert v.refresh_mode == "ON DEMAND"
        assert v.fast_refreshable is True
        assert v.last_refresh == "2025-01-01"

    def test_postgres_options_propagate(self):
        opts = ViewOptions(
            postgres=PostgresViewOptions(
                unlogged=True,
                security_definer=True,
                security_invoker=False,
            )
        )
        v = View.from_options("v", query="SELECT 1", options=opts, dialect="postgresql")

        assert v.unlogged is True
        assert v.security_definer is True
        assert v.security_invoker is False

    def test_mysql_options_propagate(self):
        opts = ViewOptions(
            mysql=MySqlViewOptions(
                algorithm="MERGE",
                sql_security="DEFINER",
                definer="root@localhost",
            )
        )
        v = View.from_options("v", query="SELECT 1", options=opts, dialect="mysql")

        assert v.algorithm == "MERGE"
        assert v.sql_security == "DEFINER"
        assert v.definer == "root@localhost"

    def test_oracle_options_propagate(self):
        opts = ViewOptions(oracle=OracleViewOptions(force=True))
        v = View.from_options("v", query="SELECT 1", options=opts, dialect="oracle")

        assert v.force is True

    def test_dependencies_propagate(self):
        opts = ViewOptions(dependencies=["table_a", "view_b"])
        v = View.from_options("v", query="SELECT 1", options=opts)

        assert v.dependencies == ["table_a", "view_b"]


# ---------------------------------------------------------------------------
# View.to_options round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToOptionsRoundTrip:
    def test_empty_view_round_trip(self):
        v = View(name="v", query="SELECT 1", dialect="postgresql")
        opts = v.to_options()
        assert opts == ViewOptions()

    def test_full_round_trip_preserves_fields(self):
        original = ViewOptions(
            materialized_view=MaterializedViewOptions(is_populated=True, refresh_method="FAST"),
            postgres=PostgresViewOptions(unlogged=True, security_invoker=True),
            mysql=MySqlViewOptions(algorithm="UNDEFINED", sql_security="INVOKER"),
            oracle=OracleViewOptions(force=False),
            dependencies=["t1", "t2"],
        )
        v = View.from_options(
            "v", query="SELECT 1", options=original, dialect="postgresql", materialized=True
        )

        rebuilt = v.to_options()
        assert rebuilt == original
