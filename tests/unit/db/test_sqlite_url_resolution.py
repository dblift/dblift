"""SQLite URL resolution must agree with SQLAlchemy's.

``sqlite:///x.db`` is the form every SQLAlchemy tutorial uses for "the file
``x.db`` next to me". dblift parsed it as RFC 3986 does — authority empty,
path ``/x.db`` — and so resolved it to the *filesystem root*. Both readings
are defensible in isolation; what is not defensible is holding both at once,
which dblift did: ``build_sqlalchemy_url`` hands the same string to
SQLAlchemy, which resolves it relatively. The SQLAlchemy engine and the
native sqlite3 connection therefore addressed different files.

SQLAlchemy's convention wins because it is the one users already know and the
one dblift's own URL builder feeds: three slashes is relative, four is
absolute.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy

from dblift.db.plugins.sqlite.sqlalchemy_url import build_sqlalchemy_url


class _Cfg:
    def __init__(self, path=None, url=None, database=None):
        self.path, self.url, self.database = path, url, database


class TestThreeSlashesIsRelative:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("sqlite:///release.db", "release.db"),
            ("sqlite:///./release.db", "./release.db"),
            ("sqlite:///data/release.db", "data/release.db"),
        ],
    )
    def test_relative_urls_stay_relative(self, url: str, expected: str) -> None:
        from dblift.db.plugins.sqlite.config import sqlite_path_from_url

        assert sqlite_path_from_url(url) == expected
        assert not os.path.isabs(sqlite_path_from_url(url))

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("sqlite:////release.db", "/release.db"),
            ("sqlite:////var/lib/dblift/release.db", "/var/lib/dblift/release.db"),
        ],
    )
    def test_four_slashes_is_absolute(self, url: str, expected: str) -> None:
        from dblift.db.plugins.sqlite.config import sqlite_path_from_url

        assert sqlite_path_from_url(url) == expected
        assert os.path.isabs(sqlite_path_from_url(url))

    def test_memory_is_preserved(self) -> None:
        from dblift.db.plugins.sqlite.config import sqlite_path_from_url

        assert sqlite_path_from_url("sqlite:///:memory:") == ":memory:"


class TestAgreementWithSqlAlchemy:
    """The bug was disagreement, so the invariant is agreement."""

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///release.db",
            "sqlite:///./release.db",
            "sqlite:///data/release.db",
            "sqlite:////release.db",
            "sqlite:////var/lib/dblift/release.db",
        ],
    )
    def test_dblift_and_sqlalchemy_resolve_the_same_file(self, url: str) -> None:
        from dblift.db.plugins.sqlite.config import sqlite_path_from_url

        sqlalchemy_path = sqlalchemy.engine.make_url(url).database
        assert os.path.abspath(sqlite_path_from_url(url)) == os.path.abspath(sqlalchemy_path)

    @pytest.mark.parametrize("path", ["release.db", "./release.db", "/var/lib/x.db"])
    def test_the_builder_round_trips_through_the_parser(self, path: str) -> None:
        """A path the builder encodes must parse back to the same file."""
        from dblift.db.plugins.sqlite.config import sqlite_path_from_url

        url = build_sqlalchemy_url(_Cfg(path=path))
        assert os.path.abspath(sqlite_path_from_url(url)) == os.path.abspath(path)
