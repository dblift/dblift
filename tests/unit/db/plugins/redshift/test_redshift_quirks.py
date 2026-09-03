"""Redshift dialect quirks."""

from dblift.db.plugins.redshift.quirks import RedshiftQuirks
from dblift.db.provider_registry import ProviderRegistry


def test_redshift_snapshot_table_uses_wide_varchar_payload() -> None:
    ddl = RedshiftQuirks().build_snapshot_table_ddl(
        '"app"."dblift_schema_snapshots"',
        snapshot_id_size=255,
        checksum_size=128,
    )

    assert "model_data VARCHAR(MAX) NOT NULL" in ddl
    assert "model_data TEXT" not in ddl


def test_redshift_uses_its_own_sqlglot_dialect_not_postgres() -> None:
    assert RedshiftQuirks().sqlglot_dialect == "redshift"


def test_redshift_distkey_sortkey_ddl_formats_without_falling_back() -> None:
    """DISTKEY/SORTKEY table-distribution clauses aren't representable in
    sqlglot's generic postgres render path (it raises on ``ast.sql()``),
    so formatting a Redshift ``CREATE TABLE ... DISTKEY(...) SORTKEY(...)``
    statement under the inherited ``"postgres"`` sqlglot dialect silently
    falls back to the original, unformatted SQL. Redshift's own sqlglot
    dialect renders it correctly.
    """
    from dblift.core.sql_generator.formatter import SqlFormatter

    ProviderRegistry.discover_plugins()
    sql = "CREATE TABLE t (id INT) DISTKEY(id) SORTKEY(id)"

    formatted = SqlFormatter(dialect="redshift").format(sql)

    assert formatted != sql
    assert "DISTKEY" in formatted
    assert "SORTKEY" in formatted
