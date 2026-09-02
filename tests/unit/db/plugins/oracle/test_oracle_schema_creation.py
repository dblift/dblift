"""Oracle schema creation regressions."""

from types import SimpleNamespace

from dblift.db.plugins.oracle.provider import OracleProvider


class _Log:
    def debug(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


def test_create_schema_uses_oracle_compatible_temporary_password(monkeypatch):
    """Oracle quoted passwords share identifier length rules on older engines."""
    provider = OracleProvider.__new__(OracleProvider)
    provider.config = SimpleNamespace(database=SimpleNamespace(username="SYSTEM"))
    provider.log = _Log()
    statements = []

    provider.execute_query = lambda *_args, **_kwargs: [{"user_count": 0}]
    provider.execute_statement = lambda sql, *args, **kwargs: statements.append(sql)

    provider.create_schema_if_not_exists("TEST_SCHEMA")

    create_user = next(sql for sql in statements if "CREATE USER" in sql)
    password_line = next(line for line in create_user.splitlines() if "IDENTIFIED BY" in line)
    password = password_line.split('"')[1]
    assert len(password) <= 30
