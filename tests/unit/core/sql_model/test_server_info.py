"""Parsing tests for :class:`core.sql_model.server_info.ServerInfo`.

The "version zoo": real-world banner strings from every probed dialect
must parse into comparable ``DatabaseVersion`` values, and anything
unparseable must degrade to ``None`` — never raise.
"""

from __future__ import annotations

import pytest

from core.sql_model.server_info import ServerInfo

pytestmark = [pytest.mark.unit]


def _version_tuple(info: ServerInfo):
    if info.version is None:
        return None
    return (info.version.major, info.version.minor, info.version.patch)


class TestFromMapping:
    def test_none_mapping_yields_empty_info(self):
        assert ServerInfo.from_mapping("mysql", None) == ServerInfo()

    def test_empty_mapping_yields_empty_info(self):
        assert ServerInfo.from_mapping("mysql", {}) == ServerInfo()

    def test_missing_keys_tolerated(self):
        info = ServerInfo.from_mapping("sqlserver", {"edition": "Standard Edition"})
        assert info.edition == "Standard Edition"
        assert info.version_raw is None
        assert info.version is None

    def test_edition_and_version_round_trip(self):
        info = ServerInfo.from_mapping(
            "sqlserver",
            {"edition": "Enterprise Edition (64-bit)", "version": "15.0.2000.5"},
        )
        assert info.edition == "Enterprise Edition (64-bit)"
        assert info.version_raw == "15.0.2000.5"
        assert _version_tuple(info) == (15, 0, 2000)

    def test_no_dialect_falls_back_to_generic_parse(self):
        info = ServerInfo.from_mapping(None, {"version": "8.0.36"})
        assert info.version_raw == "8.0.36"
        assert _version_tuple(info) == (8, 0, 36)


class TestVersionZoo:
    @pytest.mark.parametrize(
        "dialect,raw,expected",
        [
            ("postgresql", "PostgreSQL 16.2 on x86_64-pc-linux-gnu, compiled by gcc", (16, 2, 0)),
            ("mysql", "8.0.36", (8, 0, 36)),
            ("mysql", "8.0.36-0ubuntu0.22.04.1", (8, 0, 36)),
            ("mariadb", "10.11.6-MariaDB-1:10.11.6+maria~ubu2204", (10, 11, 6)),
            ("sqlserver", "15.0.2000.5", (15, 0, 2000)),
            (
                "oracle",
                "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production",
                (19, 0, 0),
            ),
            ("oracle", "Oracle Database 23ai Free Release 23.4.0.24.05", (23, 4, 0)),
            # No Release clause: the Oracle quirks override falls back to the
            # marketing version's major number.
            ("oracle", "Oracle Database 23ai Free", (23, 0, 0)),
            ("postgresql", "no digits here", None),
            ("postgresql", "", None),
        ],
    )
    def test_banner_parses(self, dialect, raw, expected):
        info = ServerInfo.from_mapping(dialect, {"version": raw})
        assert _version_tuple(info) == expected

    def test_full_version_preserves_raw_banner(self):
        info = ServerInfo.from_mapping("postgresql", {"version": "PostgreSQL 16.2 on x86_64"})
        assert info.version is not None
        assert info.version.full_version == "PostgreSQL 16.2 on x86_64"

    def test_unknown_dialect_degrades_to_unparsed(self):
        """Unknown dialects get BaseQuirks' default parser — still no raise."""
        info = ServerInfo.from_mapping("nosuchdb", {"version": "1.2.3"})
        assert info.version_raw == "1.2.3"
