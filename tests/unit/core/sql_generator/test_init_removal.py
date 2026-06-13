"""Tests pinning the 1.7.0 removal of the deprecated dialect-generator re-exports.

Action #12 PR 2 (companion to PR 1 in #358): the 10 dialect-generator names
that ``core/sql_generator/__init__.py`` used to re-export from
``db/plugins/<X>/generator/`` — and the 5 ALTER subset re-exported from
``core/sql_generator/alter/__init__.py`` — are now removed outright.
Consumers must import directly from the plugin path:

    from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator
    from db.plugins.mysql.generator.alter_generator import MySQLAlterGenerator

These tests assert the legacy access path is gone — both at the
``__all__`` declaration level and at runtime via attribute lookup. They
also confirm the canonical plugin-path imports still work.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestLegacyReexportsRemoved:
    """Pin that the 1.7.0 removal landed cleanly."""

    LEGACY_TOP_LEVEL_NAMES = (
        "DB2AlterGenerator",
        "DB2SqlGenerator",
        "MySQLAlterGenerator",
        "MySQLSqlGenerator",
        "OracleAlterGenerator",
        "OracleSqlGenerator",
        "PostgreSQLAlterGenerator",
        "PostgreSQLSqlGenerator",
        "SQLServerAlterGenerator",
        "SQLServerSqlGenerator",
    )

    LEGACY_ALTER_NAMES = (
        "DB2AlterGenerator",
        "MySQLAlterGenerator",
        "OracleAlterGenerator",
        "PostgreSQLAlterGenerator",
        "SQLServerAlterGenerator",
    )

    def test_legacy_names_removed_from_top_level_all(self):
        """The 10 legacy names must not appear in
        ``core.sql_generator.__all__`` — that's the surface contract."""
        from core import sql_generator

        for name in self.LEGACY_TOP_LEVEL_NAMES:
            assert name not in sql_generator.__all__, f"{name} still in __all__"

    def test_legacy_names_unreachable_via_top_level_attribute_access(self):
        """``core.sql_generator.PostgreSQLSqlGenerator`` must now raise
        ``AttributeError`` — the PEP 562 ``__getattr__`` shim from PR 1
        is gone."""
        from core import sql_generator

        for name in self.LEGACY_TOP_LEVEL_NAMES:
            with pytest.raises(AttributeError):
                getattr(sql_generator, name)

    def test_legacy_names_removed_from_alter_all(self):
        from core.sql_generator import alter

        for name in self.LEGACY_ALTER_NAMES:
            assert name not in alter.__all__, f"{name} still in alter.__all__"

    def test_legacy_names_unreachable_via_alter_attribute_access(self):
        from core.sql_generator import alter

        for name in self.LEGACY_ALTER_NAMES:
            with pytest.raises(AttributeError):
                getattr(alter, name)

    def test_canonical_plugin_paths_still_work(self):
        """The actual import path that consumers should migrate to."""
        from db.plugins.db2.generator.alter_generator import DB2AlterGenerator
        from db.plugins.db2.generator.ddl_generator import DB2SqlGenerator
        from db.plugins.mysql.generator.alter_generator import MySQLAlterGenerator
        from db.plugins.mysql.generator.ddl_generator import MySQLSqlGenerator
        from db.plugins.oracle.generator.alter_generator import OracleAlterGenerator
        from db.plugins.oracle.generator.ddl_generator import OracleSqlGenerator
        from db.plugins.postgresql.generator.alter_generator import PostgreSQLAlterGenerator
        from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator
        from db.plugins.sqlserver.generator.alter_generator import SQLServerAlterGenerator
        from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator

        # Sanity: each is a class.
        for cls in (
            DB2AlterGenerator,
            DB2SqlGenerator,
            MySQLAlterGenerator,
            MySQLSqlGenerator,
            OracleAlterGenerator,
            OracleSqlGenerator,
            PostgreSQLAlterGenerator,
            PostgreSQLSqlGenerator,
            SQLServerAlterGenerator,
            SQLServerSqlGenerator,
        ):
            assert isinstance(cls, type), f"{cls!r} should be a class"
