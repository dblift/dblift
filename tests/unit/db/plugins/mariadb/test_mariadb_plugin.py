"""MariaDB plugin unit tests.

Verifies that the MariaDB plugin is correctly registered as a native
transport, inherits MySQL-family behavior, and preserves MariaDB-specific
quirks (requires_rollback_after_introspection=False, JSON type mapping).
"""

from db.plugins.mariadb.plugin import PLUGIN as MARIADB_PLUGIN
from db.plugins.mariadb.provider import MariadbProvider
from db.plugins.mariadb.quirks import MariadbQuirks
from db.plugins.mysql.provider import MySqlProvider
from db.sqlalchemy_provider import SqlAlchemyProvider


def test_mariadb_plugin_is_native_transport() -> None:
    """Plugin declares native transport."""
    assert MARIADB_PLUGIN.transport == "native"
    assert MARIADB_PLUGIN.sqlalchemy_url_builder is not None


def test_mariadb_provider_inherits_mysql() -> None:
    """MariadbProvider inherits from MySqlProvider (and therefore SqlAlchemyProvider)."""
    assert issubclass(MariadbProvider, MySqlProvider)
    assert issubclass(MariadbProvider, SqlAlchemyProvider)


def test_mariadb_provider_has_correct_dialect_key() -> None:
    """MariaDB declares its own canonical dialect key."""
    assert MariadbProvider.canonical_dialect_key == "mariadb"


def test_mariadb_provider_does_not_own_snapshot_hooks() -> None:
    """MariaDB does not define provider-owned snapshot hooks."""
    assert "supports_snapshots" not in MariadbProvider.__dict__
    assert "create_snapshot_table_if_not_exists" not in MariadbProvider.__dict__
    assert "create_snapshot_table_if_not_exists" not in MariadbProvider.__abstractmethods__


def test_mariadb_quirks_reject_snapshot_table_ddl() -> None:
    """MariaDB quirks do not inherit MySQL snapshot table DDL."""
    import pytest

    with pytest.raises(NotImplementedError, match="MariaDB snapshots are not provider-owned"):
        MariadbQuirks().build_snapshot_table_ddl("app.dblift_schema_snapshots", 128, 64)


def test_mariadb_quirks_no_rollback_after_introspection() -> None:
    """MariaDB does not require post-introspection rollback (unlike MySQL)."""
    quirks = MariadbQuirks()
    assert quirks.requires_rollback_after_introspection is False


def test_mariadb_quirks_json_type_mapping() -> None:
    """MariaDB 10.2+ JSON type is mapped in version_specific_type_mappings."""
    assert ("mariadb", "10.2+") in MariadbQuirks.version_specific_type_mappings


def test_mariadb_plugin_sqlalchemy_url_builder_rejects_jdbc() -> None:
    """URL builder rejects legacy legacy URLs on the native path."""
    from types import SimpleNamespace

    import pytest

    db = SimpleNamespace(
        type="mariadb",
        url="jdbc:mysql://db.example.com:3306/app",
    )
    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        MARIADB_PLUGIN.sqlalchemy_url_builder(db)


def test_mariadb_plugin_sqlalchemy_url_builder_builds_pymysql_url() -> None:
    """URL builder produces a mysql+pymysql URL for field-based configs."""
    from types import SimpleNamespace

    from sqlalchemy.engine import make_url

    db = SimpleNamespace(
        type="mariadb",
        host="db.example.com",
        port=3306,
        database="app",
        username="maria",
        password="secret",
        ssl_enabled=False,
        connection_timeout=None,
        options=None,
        extra_params=None,
        session_variables=None,
        url=None,
    )
    url = make_url(MARIADB_PLUGIN.sqlalchemy_url_builder(db))
    assert url.drivername == "mysql+pymysql"
    assert url.host == "db.example.com"
    assert url.database == "app"
    assert url.username == "maria"


def test_mariadb_has_no_provider_compat_snapshot_ddl():
    from db.plugins.mariadb.quirks import MariadbQuirks

    assert MariadbQuirks().build_provider_compat_snapshot_ddl("db.snap", 100, 128) is None


def test_mariadb_does_not_skip_existence_check():
    from db.plugins.mariadb.quirks import MariadbQuirks

    # Must override the True it would inherit from MysqlQuirks, else a real
    # MariadbProvider would skip the existence check and then raise.
    assert MariadbQuirks().provider_compat_snapshot_skips_existence_check is False
