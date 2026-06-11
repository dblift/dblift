"""SQL Server plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from db.plugins.sqlserver.plugin import PLUGIN as SQLSERVER_PLUGIN


def _db(**kw):
    defaults = dict(
        type="sqlserver",
        host=None,
        port=None,
        database=None,
        username=None,
        password=None,
        url=None,
        instance=None,
        connection_timeout=None,
        extra_params=None,
        options=None,
        encrypt=False,
        trust_server_certificate=False,
        integrated_security=False,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_plugin_declares_sqlalchemy_url_builder():
    assert SQLSERVER_PLUGIN.sqlalchemy_url_builder is not None
    assert SQLSERVER_PLUGIN.transport == "native"


def test_field_based_url_builds_pymssql():
    db = _db(host="h", port=1433, database="app", username="u", password="p")
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.drivername == "mssql+pymssql"
    assert url.host == "h"
    assert url.port == 1433
    assert url.database == "app"
    assert url.username == "u"
    assert url.password == "p"


def test_raw_sqlalchemy_url_forwarded():
    db = _db(url="mssql+pymssql://u:p@h:1433/app")
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.drivername == "mssql+pymssql"
    assert url.host == "h"


def test_bare_mssql_url_uses_pymssql_driver():
    db = _db(url="mssql://u:p@h:1433/app")
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.drivername == "mssql+pymssql"
    assert url.host == "h"


def test_database_url_raises():
    db = _db(url="jdbc:sqlserver://h:1433;databaseName=app")
    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        SQLSERVER_PLUGIN.sqlalchemy_url_builder(db)


def test_instance_in_host():
    db = _db(host="h", database="app", instance="SQLEXPRESS", username="u", password="p")
    url_str = SQLSERVER_PLUGIN.sqlalchemy_url_builder(db)
    assert "SQLEXPRESS" in url_str


def test_merge_credentials_into_raw_url():
    db = _db(url="mssql+pymssql://h/app", username="u", password="secret")
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.username == "u"
    assert url.password == "secret"


def test_raw_url_prefers_explicit_credentials_over_url_userinfo():
    db = _db(
        url="mssql+pymssql://stale:old@h/app",
        username="u",
        password="secret",
    )
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.username == "u"
    assert url.password == "secret"


def test_field_based_url_preserves_query_options():
    db = _db(
        host="h",
        database="app",
        connection_timeout=12,
        extra_params={"appname": "dblift"},
        options={"charset": "utf8"},
    )
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.query["login_timeout"] == "12"
    assert url.query["appname"] == "dblift"
    assert url.query["charset"] == "utf8"
    assert url.query["encryption"] == "off"


def test_raw_sqlalchemy_url_preserves_query_options():
    db = _db(
        url="mssql+pymssql://h/app?tds_version=7.4",
        connection_timeout=12,
        extra_params={"appname": "dblift"},
    )
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.query["tds_version"] == "7.4"
    assert url.query["login_timeout"] == "12"
    assert url.query["appname"] == "dblift"
    assert url.query["encryption"] == "off"


def test_raw_encrypt_query_maps_to_pymssql_encryption():
    db = _db(url="mssql+pymssql://h/app?encrypt=true")
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.query["encryption"] == "require"
    assert "encrypt" not in url.query


def test_extra_params_encrypt_maps_to_pymssql_encryption():
    db = _db(host="h", database="app", extra_params={"encrypt": "true"})
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.query["encryption"] == "require"
    assert "encrypt" not in url.query


def test_encrypt_true_maps_to_pymssql_encryption_require():
    db = _db(host="h", database="app", encrypt=True)
    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))
    assert url.query["encryption"] == "require"


def test_integrated_security_raises_for_native_pymssql():
    db = _db(host="h", database="app", integrated_security=True)
    with pytest.raises(ValueError, match="do not support integrated_security"):
        SQLSERVER_PLUGIN.sqlalchemy_url_builder(db)


def test_raw_integrated_security_query_raises_for_native_pymssql():
    db = _db(url="mssql+pymssql://h/app?integratedSecurity=true")
    with pytest.raises(ValueError, match="do not support integrated_security"):
        SQLSERVER_PLUGIN.sqlalchemy_url_builder(db)


def test_trust_server_certificate_raises_for_native_pymssql():
    db = _db(host="h", database="app", trust_server_certificate=True)
    with pytest.raises(ValueError, match="do not support trust_server_certificate"):
        SQLSERVER_PLUGIN.sqlalchemy_url_builder(db)


def test_url_builds_with_supported_options():
    raw = {
        "url": "mssql+pymssql://localhost:1433/dblift?encryption=off",
        "username": "sa",
        "password": "secret",
    }
    db = _db(
        url=raw["url"],
        username=raw["username"],
        password=raw["password"],
        extra_params={},
    )

    url = make_url(SQLSERVER_PLUGIN.sqlalchemy_url_builder(db))

    assert url.database == "dblift"
    assert url.query["encryption"] == "off"
    assert "trustServerCertificate" not in url.query
