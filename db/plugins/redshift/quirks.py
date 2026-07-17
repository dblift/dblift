"""Redshift :class:`DialectQuirks` - inherits PostgreSQL behavior."""

from __future__ import annotations

from db.plugins.postgresql.quirks import PostgresqlQuirks


class RedshiftQuirks(PostgresqlQuirks):
    """Redshift quirks, inheriting PostgreSQL behavior."""

    is_ansi_reference_dialect = False
    is_default_sqlglot_read_fallback = False

    def __init__(self, dialect_name: str = "redshift") -> None:
        super().__init__(dialect_name=dialect_name)

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Render snapshot storage with Redshift's widest VARCHAR payload column."""
        return (
            f"CREATE TABLE {qualified_table} ("
            f"snapshot_id VARCHAR({snapshot_id_size}) PRIMARY KEY, "
            f"captured_at VARCHAR({snapshot_id_size}) NOT NULL, "
            f"checksum VARCHAR({checksum_size}) NOT NULL, "
            f"model_data VARCHAR(MAX) NOT NULL)"
        )


__all__ = ["RedshiftQuirks"]
