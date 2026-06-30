from sqlalchemy import text

import db.native_connection_manager as connection_manager_module
from db.native_connection_manager import NativeConnectionManager


class _DB:
    type = "sqlite"
    path = ":memory:"


class _Cfg:
    database = _DB()


def test_creates_usable_connection():
    mgr = NativeConnectionManager(_Cfg())
    conn = mgr.create_connection()
    assert conn.execute(text("SELECT 1")).scalar() == 1
    mgr.close()


def test_engine_is_reused_across_connections():
    mgr = NativeConnectionManager(_Cfg())
    mgr.create_connection()
    e1 = mgr.engine
    mgr.create_connection()
    assert mgr.engine is e1
    mgr.close()


def test_close_disposes_engine():
    mgr = NativeConnectionManager(_Cfg())
    mgr.create_connection()
    mgr.close()
    assert mgr._engine is None


def test_create_connection_closes_previous():
    mgr = NativeConnectionManager(_Cfg())
    c1 = mgr.create_connection()
    c2 = mgr.create_connection()
    assert c1.closed is True  # previous connection must not leak
    assert c2.closed is False
    mgr.close()


def test_mysql_engine_disables_pool_reset_on_return(monkeypatch):
    class _MySqlDB:
        type = "mysql"

    class _MySqlCfg:
        database = _MySqlDB()

    calls = {}
    fake_engine = object()

    monkeypatch.setattr(
        connection_manager_module.ProviderRegistry,
        "build_sqlalchemy_url",
        lambda database: "mysql+pymysql://root:root@127.0.0.1:3307/testdb",
    )

    def fake_create_engine(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return fake_engine

    monkeypatch.setattr(connection_manager_module, "create_engine", fake_create_engine)

    mgr = NativeConnectionManager(_MySqlCfg())

    assert mgr.engine is fake_engine
    assert calls["kwargs"] == {
        "pool_pre_ping": True,
        "future": True,
        "pool_reset_on_return": None,
    }


def test_non_mysql_engine_keeps_default_pool_reset(monkeypatch):
    calls = {}
    fake_engine = object()

    monkeypatch.setattr(
        connection_manager_module.ProviderRegistry,
        "build_sqlalchemy_url",
        lambda database: "sqlite:///:memory:",
    )

    def fake_create_engine(url, **kwargs):
        calls["kwargs"] = kwargs
        return fake_engine

    monkeypatch.setattr(connection_manager_module, "create_engine", fake_create_engine)

    mgr = NativeConnectionManager(_Cfg())

    assert mgr.engine is fake_engine
    assert calls["kwargs"] == {"pool_pre_ping": True, "future": True}


def test_engine_options_mysql_includes_pool_reset():
    class _MySqlDB:
        type = "mysql"

    class _MySqlCfg:
        database = _MySqlDB()

    mgr = NativeConnectionManager(_MySqlCfg())
    options = mgr._engine_options()
    assert options == {
        "pool_pre_ping": True,
        "future": True,
        "pool_reset_on_return": None,
    }


def test_engine_options_postgresql_omits_pool_reset():
    class _PgDB:
        type = "postgresql"

    class _PgCfg:
        database = _PgDB()

    mgr = NativeConnectionManager(_PgCfg())
    options = mgr._engine_options()
    assert options == {"pool_pre_ping": True, "future": True}
    assert "pool_reset_on_return" not in options
