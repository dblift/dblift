"""Conformance tests for version/edition feature gates.

Plugins declare :class:`db.feature_gate.FeatureGate` entries on their
quirks classes; ``core.sql_model.feature_gates`` derives the lazy registry
and resolves them tri-state. These tests enforce the declaration
invariants (names in the shared vocabulary, parseable specs, compilable
patterns) and pin the per-dialect contracts, mirroring
``test_dialect_capabilities.py``.
"""

from __future__ import annotations

import re

import pytest

from core.introspection.version_detector import parse_version
from core.sql_model.feature_gates import (
    KNOWN_FEATURES,
    FeatureGate,
    get_feature_gates,
    supports_feature,
)

pytestmark = [pytest.mark.unit]


def _plugins():
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    return sorted(ProviderRegistry.list_plugins(), key=lambda p: p.name)


def _plugin_names():
    return [p.name for p in _plugins()]


# --- Declaration invariants --------------------------------------------------


class TestDeclarationInvariants:
    @pytest.mark.parametrize("dialect", _plugin_names())
    def test_gate_names_are_known_features(self, dialect):
        """Every declared gate key belongs to the shared vocabulary (typo guard)."""
        for feature in get_feature_gates(dialect):
            assert feature in KNOWN_FEATURES, (dialect, feature)

    @pytest.mark.parametrize("dialect", _plugin_names())
    def test_version_specs_parse(self, dialect):
        for feature, gate in get_feature_gates(dialect).items():
            for spec in (gate.min_version, gate.removed_in):
                if spec is not None:
                    assert parse_version(spec.rstrip("+")) is not None, (dialect, feature, spec)

    @pytest.mark.parametrize("dialect", _plugin_names())
    def test_edition_patterns_compile(self, dialect):
        for feature, gate in get_feature_gates(dialect).items():
            if gate.edition_pattern is not None:
                re.compile(gate.edition_pattern, re.IGNORECASE)

    @pytest.mark.parametrize("dialect", _plugin_names())
    def test_gates_have_descriptions(self, dialect):
        for feature, gate in get_feature_gates(dialect).items():
            assert gate.description, (dialect, feature)

    def test_gate_dataclass_is_frozen(self):
        gate = FeatureGate(min_version="1.0+")
        with pytest.raises(Exception):
            gate.min_version = "2.0+"  # type: ignore[misc]


# --- Per-dialect declaration contracts ---------------------------------------


class TestDeclaredGates:
    def test_sqlserver_declares_online_index_build(self):
        gate = get_feature_gates("sqlserver")["online_index_build"]
        assert gate.edition_pattern == r"enterprise|developer|evaluation|azure"

    def test_oracle_declares_online_index_build(self):
        gate = get_feature_gates("oracle")["online_index_build"]
        assert gate.edition_pattern == r"enterprise"

    def test_mysql_declares_rename_column(self):
        gate = get_feature_gates("mysql")["rename_column"]
        assert gate.min_version == "8.0+"

    def test_mariadb_redeclares_rename_column(self):
        """``feature_gates`` replaces the parent dict wholesale — MariaDB must
        restate ``rename_column`` with its own threshold (inheritance guard)."""
        gate = get_feature_gates("mariadb")["rename_column"]
        assert gate.min_version == "10.5.2+"

    def test_postgresql_declares_set_not_null_reuses_validated_check(self):
        gate = get_feature_gates("postgresql")["set_not_null_reuses_validated_check"]
        assert gate.min_version == "12.0+"

    @pytest.mark.parametrize(
        "alias", ["aurora-postgresql", "neon", "supabase", "alloydb", "timescaledb", "citus"]
    )
    def test_true_pg_family_inherits_postgresql_gates(self, alias):
        """Factory-built PG-compatible quirks inherit PostgreSQL's gates —
        these engines run a real PostgreSQL server, so PG version semantics
        transfer."""
        assert "set_not_null_reuses_validated_check" in get_feature_gates(alias)

    def test_redshift_declares_no_gates(self):
        """Redshift opts out (redeclared empty): its engine diverged from PG
        long ago and its version() banner even reports PostgreSQL 8.0.x."""
        assert dict(get_feature_gates("redshift")) == {}

    def test_cockroachdb_declares_no_gates(self):
        """CockroachDB opts out (redeclared empty): v23.x would read as
        ">= 12" to a naive comparison — the wrong-signal guard."""
        assert dict(get_feature_gates("cockroachdb")) == {}


# --- Resolver tri-state matrix -----------------------------------------------


class TestSupportsFeature:
    @pytest.mark.parametrize(
        "edition,expected",
        [
            ("Enterprise Edition: Core-based Licensing (64-bit)", True),
            ("Developer Edition (64-bit)", True),
            ("Evaluation Edition", True),
            ("SQL Azure", True),
            ("Standard Edition (64-bit)", False),
            ("Express Edition", False),
            (None, None),
        ],
    )
    def test_sqlserver_online_index_by_edition(self, edition, expected):
        server_info = {"edition": edition} if edition is not None else {}
        assert supports_feature("sqlserver", "online_index_build", server_info) is expected

    def test_sqlserver_version_only_is_unknown(self):
        """Partial knowledge: an edition-gated feature with version-only info."""
        result = supports_feature("sqlserver", "online_index_build", {"version": "15.0.2000.5"})
        assert result is None

    @pytest.mark.parametrize(
        "banner,expected",
        [
            ("Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production", True),
            ("Oracle Database 19c Standard Edition 2 Release 19.0.0.0.0", False),
        ],
    )
    def test_oracle_online_index_by_banner(self, banner, expected):
        assert supports_feature("oracle", "online_index_build", {"edition": banner}) is expected

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("8.0.36", True),
            ("8.0.36-0ubuntu0.22.04.1", True),
            ("5.7.44-log", False),
            ("garbage", None),
            (None, None),
        ],
    )
    def test_mysql_rename_column_by_version(self, version, expected):
        server_info = {"version": version} if version is not None else None
        assert supports_feature("mysql", "rename_column", server_info) is expected

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("10.5.2", True),  # exact boundary, patch-level comparison
            ("10.11.6-MariaDB-1:10.11.6+maria~ubu2204", True),
            ("10.4.13", False),
        ],
    )
    def test_mariadb_rename_column_by_version(self, version, expected):
        assert supports_feature("mariadb", "rename_column", {"version": version}) is expected

    @pytest.mark.parametrize(
        "version,expected",
        [
            ("PostgreSQL 12.0 on x86_64", True),  # exact boundary
            ("PostgreSQL 12.4 on x86_64-pc-linux-gnu", True),
            ("PostgreSQL 16.2 on x86_64", True),
            ("PostgreSQL 11.9 on x86_64", False),
            (None, None),
        ],
    )
    def test_postgresql_set_not_null_by_version(self, version, expected):
        server_info = {"version": version} if version is not None else None
        result = supports_feature("postgresql", "set_not_null_reuses_validated_check", server_info)
        assert result is expected

    def test_cockroachdb_own_versioning_never_matches_pg_gate(self):
        """CockroachDB v23.x must NOT resolve the PG gate to True (opted out)."""
        result = supports_feature(
            "cockroachdb",
            "set_not_null_reuses_validated_check",
            {"version": "CockroachDB CCL v23.1.11"},
        )
        assert result is None

    def test_unknown_dialect_is_unknown(self):
        assert supports_feature("nosuchdb", "online_index_build", {"edition": "x"}) is None
        assert supports_feature(None, "online_index_build", {"edition": "x"}) is None

    def test_undeclared_feature_is_unknown(self):
        assert supports_feature("postgresql", "online_index_build", {"version": "16.2"}) is None

    def test_inherited_empty_gates_are_unknown(self):
        """Redshift inherits PostgresqlQuirks' empty ``feature_gates``."""
        assert supports_feature("redshift", "online_index_build", {"edition": "x"}) is None

    def test_combine_semantics(self):
        """Zero constraints -> True; any False wins over None; None over True."""
        from core.sql_model.feature_gates import _combine

        assert _combine() is True
        assert _combine(True, True) is True
        assert _combine(True, None) is None
        assert _combine(True, None, False) is False

    def test_never_raises_on_hostile_input(self):
        assert supports_feature("mysql", "rename_column", {"version": object()}) in (
            True,
            False,
            None,
        )


# --- Registry invalidation ---------------------------------------------------


class TestRegistryRebuild:
    def test_counter_based_rebuild_survives_alias_dedup(self):
        """Shared aliases (mysql/mariadb) dedupe the dict; the counter — not
        ``len()`` — must still converge (PR #241 idiom)."""
        import core.sql_model.feature_gates as fg

        fg._FEATURE_GATES.clear()
        fg._feature_gates_seen = 0
        first = supports_feature("mariadb", "rename_column", {"version": "10.5.2"})
        second = supports_feature("mariadb", "rename_column", {"version": "10.5.2"})
        assert first is True and second is True
        assert fg._feature_gates_seen > 0
