"""``table_exists`` must see a table the connected role cannot read."""

from dblift.db.plugins.postgresql.provider import PostgreSqlProvider


class _Provider(PostgreSqlProvider):
    def __init__(self):
        self.sql = []

    def execute_query(self, sql, params=None):
        self.sql.append(sql)
        return [{"exists": True}]


def test_table_exists_does_not_hide_tables_the_role_cannot_select():
    """``information_schema.tables`` lists only tables the role holds a privilege
    on, so a history table without SELECT reads as absent and ``info`` reports
    every migration pending. The system catalog lists it regardless of privilege."""
    provider = _Provider()

    assert provider.table_exists("app", "dblift_schema_history") is True

    assert "information_schema" not in provider.sql[0]
    assert "pg_class" in provider.sql[0]
