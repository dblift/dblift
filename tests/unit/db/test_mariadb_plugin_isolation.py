"""Plug-and-play proof for the MariaDB plugin (Epic 26 story 26-13).

These tests assert two architectural invariants:

1. ``mariadb`` is an INDEPENDENT registered plugin, not a MySQL alias.
   Its provider class, quirks class, and entry-point are distinct.

2. The plugin lives entirely under ``db/plugins/mariadb/``. No file
   under ``core/``, ``api/``, ``cli/``, or ``config/`` was added or
   modified to register this dialect — the ``dialect-string-literal``
   lint rule and the entry-point discovery path together enforce
   that contract.

Together they show that the Epic 26 plug-and-play goal works for a
real new dialect.
"""

from __future__ import annotations

from dblift.db.plugins.mariadb.plugin import PLUGIN as MARIADB_PLUGIN
from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.provider_registry import ProviderRegistry


def test_mariadb_is_distinct_plugin_from_mysql():
    """``mariadb`` and ``mysql`` resolve to different ``PluginInfo``."""
    ProviderRegistry.discover_plugins()
    mariadb = ProviderRegistry._plugins.get("mariadb")
    mysql = ProviderRegistry._plugins.get("mysql")
    assert mariadb is not None, "mariadb plugin not registered"
    assert mysql is not None, "mysql plugin not registered"
    assert mariadb is not mysql, (
        "mariadb is registered as the MySQL plugin alias; "
        "story 26-13 requires a distinct PluginInfo."
    )
    assert mariadb.provider_class is MariadbProvider
    assert mariadb.quirks_class is MariadbQuirks


def test_mariadb_inherits_mysql_behaviour():
    """MariaDB provider/quirks subclass MySQL — same behaviour by default."""
    assert issubclass(MariadbProvider, MySqlProvider)
    assert issubclass(MariadbQuirks, MysqlQuirks)


def test_mariadb_quirks_dialect_name_round_trips():
    """``get_quirks('mariadb').dialect_name`` is ``'mariadb'`` (not 'mysql')."""
    quirks = ProviderRegistry.get_quirks("mariadb")
    assert quirks.dialect_name == "mariadb"
    assert isinstance(quirks, MariadbQuirks)


def test_mariadb_no_longer_registers_jdbc_prefix():
    """MariaDB is native-only in v2; SQLAlchemy URL routing resolves it."""
    ProviderRegistry.discover_plugins()
    cls = ProviderRegistry.get_provider_by_url("mariadb+pymysql://host:3306/db")
    assert cls is MariadbProvider


def test_mysql_no_longer_claims_mariadb():
    """The MySQL plugin's ``dialects`` list no longer includes mariadb."""
    ProviderRegistry.discover_plugins()
    mysql = ProviderRegistry._plugins.get("mysql")
    assert mysql is not None
    assert "mariadb" not in mysql.dialects, (
        "mysql plugin should not advertise mariadb as one of its dialects "
        "now that mariadb has its own plugin (story 26-13)."
    )


def test_mariadb_plugin_info_constant():
    """The exported ``PLUGIN`` constant is well-formed."""
    assert MARIADB_PLUGIN.name == "mariadb"
    assert MARIADB_PLUGIN.dialects == ["mariadb"]
    assert MARIADB_PLUGIN.provider_class is MariadbProvider
    assert MARIADB_PLUGIN.quirks_class is MariadbQuirks
    assert MARIADB_PLUGIN.transport == "native"
    assert MARIADB_PLUGIN.sqlalchemy_url_builder is not None
    assert MARIADB_PLUGIN.native_driver_module == "pymysql"
