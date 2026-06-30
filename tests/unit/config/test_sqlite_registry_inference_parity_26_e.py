"""ADR-26 E parity tests: sqlite type inference derived from the plugin registry.

These pin the exact behaviour of the 8 URL-scheme inference sites that
hardcoded ``"sqlite"`` before they were switched to a registry-derived value.
They must stay green across the refactor (behaviour-preserving).

Parity matrix (every case must resolve to type ``sqlite``):
    sqlite:///abs/path.db, sqlite:///./rel.db, sqlite:///:memory:,
    sqlite:// (bare), sqlite3:///x.db (alias -> sqlite).
Non-sqlite native URLs (postgresql://, mysql://) keep their own type;
unknown/legacy (jdbc:) unchanged.
"""

import pytest

from config.config_builder import ConfigBuilder
from config.database_config import (
    _infer_type_from_uri,
    _infer_type_from_url_scheme,
)
from config.dblift_config import DbliftConfig
from db.plugins.sqlserver.config import SqlServerConfig  # relocated per ADR-26 D

SQLITE_URLS = [
    "sqlite:///abs/path.db",
    "sqlite:///./rel.db",
    "sqlite:///:memory:",
    "sqlite://",
    "sqlite3:///x.db",
]

# Subset that yields a *buildable* SQLiteConfig. Bare ``sqlite://`` infers
# type=sqlite at the inference sites but SQLiteConfig still rejects it (no
# path) at construction time — that pre-existing behaviour is asserted
# separately so the refactor preserves it exactly.
SQLITE_URLS_BUILDABLE = [
    "sqlite:///abs/path.db",
    "sqlite:///./rel.db",
    "sqlite:///:memory:",
    "sqlite3:///x.db",
]

NON_SQLITE_NATIVE = [
    ("postgresql://user:pass@localhost/db", "postgresql"),
    ("mysql://user:pass@localhost/db", "mysql"),
]


@pytest.mark.unit
class TestInferTypeFromUrlScheme:
    """Site: database_config._infer_type_from_url_scheme (was line 76)."""

    @pytest.mark.parametrize("url", SQLITE_URLS)
    def test_sqlite_urls_infer_sqlite(self, url):
        data = {"url": url}
        _infer_type_from_url_scheme(data)
        assert data["type"] == "sqlite"

    @pytest.mark.parametrize("url,expected", NON_SQLITE_NATIVE)
    def test_native_non_sqlite_urls(self, url, expected):
        data = {"url": url}
        _infer_type_from_url_scheme(data)
        assert data["type"] == expected

    def test_jdbc_url_left_unset(self):
        data = {"url": "jdbc:sqlite:/tmp/x.db"}
        _infer_type_from_url_scheme(data)
        assert "type" not in data or data["type"] == ""

    def test_existing_type_not_overwritten(self):
        data = {"type": "postgresql", "url": "sqlite:///x.db"}
        _infer_type_from_url_scheme(data)
        assert data["type"] == "postgresql"


@pytest.mark.unit
class TestInferTypeFromUri:
    """Site: database_config._infer_type_from_uri (was lines 114, 116)."""

    @pytest.mark.parametrize("url", SQLITE_URLS)
    def test_sqlite_uris_infer_sqlite(self, url):
        data = {}
        _infer_type_from_uri(data, url)
        assert data["type"] == "sqlite"

    @pytest.mark.parametrize("url,expected", NON_SQLITE_NATIVE)
    def test_native_non_sqlite_uris(self, url, expected):
        data = {}
        _infer_type_from_uri(data, url)
        assert data["type"] == expected


@pytest.mark.unit
class TestConfigBuilderApplyOverridesToCopy:
    """Site: config_builder._apply_overrides_to_copy (was line 152)."""

    def _base(self):
        return SqlServerConfig(
            type="sqlserver",
            url="mssql+pymssql://localhost:1433/master",
            username="sa",
            password="pass",
            schema="dbo",
        )

    @pytest.mark.parametrize("url", SQLITE_URLS)
    def test_sqlite_url_forces_sqlite_type(self, url):
        result = ConfigBuilder._apply_overrides_to_copy(self._base(), {"url": url})
        assert result.type == "sqlite"

    def test_non_sqlite_url_keeps_base_type(self):
        result = ConfigBuilder._apply_overrides_to_copy(
            self._base(), {"url": "mssql+pymssql://localhost:1433/mydb"}
        )
        assert result.type == "sqlserver"


@pytest.mark.unit
class TestConfigBuilderTryCreateSqliteConfig:
    """Site: config_builder._try_create_sqlite_config (was line 173)."""

    def _base(self):
        return SqlServerConfig(
            type="sqlserver",
            url="mssql+pymssql://localhost:1433/master",
            username="sa",
            password="pass",
            schema="dbo",
        )

    @pytest.mark.parametrize("url", SQLITE_URLS_BUILDABLE)
    def test_sqlite_url_creates_sqlite_config(self, url):
        result = ConfigBuilder._try_create_sqlite_config({"url": url}, self._base())
        assert result is not None
        assert result.type == "sqlite"

    def test_bare_sqlite_url_returns_none(self):
        # Bare sqlite:// is recognised as sqlite-ish but cannot build a
        # SQLiteConfig (no path) → the helper swallows the ValueError → None.
        result = ConfigBuilder._try_create_sqlite_config({"url": "sqlite://"}, self._base())
        assert result is None

    def test_non_sqlite_url_returns_none(self):
        result = ConfigBuilder._try_create_sqlite_config(
            {"url": "postgresql://localhost/db"}, self._base()
        )
        assert result is None


@pytest.mark.unit
class TestDbliftConfigFromDict:
    """Site: dblift_config.from_dict sqlite inference (was line 681)."""

    @pytest.mark.parametrize("url", SQLITE_URLS_BUILDABLE)
    def test_sqlite_url_creates_sqlite(self, url):
        cfg = DbliftConfig.from_dict({"database": {"url": url}})
        assert cfg.database.type == "sqlite"

    @pytest.mark.parametrize("url,expected", NON_SQLITE_NATIVE)
    def test_native_non_sqlite_url(self, url, expected):
        cfg = DbliftConfig.from_dict({"database": {"url": url, "username": "u", "password": "p"}})
        assert cfg.database.type == expected


@pytest.mark.unit
class TestDbliftConfigValidateCompleteData:
    """Site: dblift_config.validate_complete_data sqlite inference (was line 859)."""

    @pytest.mark.parametrize("url", SQLITE_URLS)
    def test_sqlite_url_validates(self, url):
        # Should not raise — a sqlite URL produces a valid connection identifier.
        DbliftConfig.validate_complete_data({"database": {"url": url}})

    @pytest.mark.parametrize("url,_expected", NON_SQLITE_NATIVE)
    def test_native_non_sqlite_url_validates(self, url, _expected):
        DbliftConfig.validate_complete_data({"database": {"url": url}})


@pytest.mark.unit
class TestDbliftConfigFromArgsDict:
    """Site: dblift_config.from_args_dict sqlite inference (was line 1061)."""

    @pytest.mark.parametrize("url", SQLITE_URLS)
    def test_sqlite_url_infers_sqlite(self, url):
        out = DbliftConfig.from_args_dict({"db_url": url})
        assert out["database"]["type"] == "sqlite"

    @pytest.mark.parametrize("url,expected", NON_SQLITE_NATIVE)
    def test_native_non_sqlite_url(self, url, expected):
        out = DbliftConfig.from_args_dict({"db_url": url})
        assert out["database"]["type"] == expected
