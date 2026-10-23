"""A PL/SQL unit Oracle compiles with errors (ORA-24344) is a failed statement."""

from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from sqlalchemy import create_engine

from dblift.core.exceptions import ExecutionError
from dblift.db.plugins.oracle.provider import OracleProvider

BAD_PROC = "CREATE OR REPLACE PROCEDURE bad_p AS BEGIN no_such_proc(1); END;"


class _Warning:
    """Shaped like python-oracledb's warning: thin mode reports ``DPY-7000`` with code 0."""

    def __init__(self, full_code: str) -> None:
        self.code = 0
        self.full_code = full_code


class _Cursor:
    def __init__(self, warning: Optional[_Warning]) -> None:
        self.warning = warning


class _Provider(OracleProvider):
    """Provider whose driver cursor reports ``warning`` after every execute."""

    def __init__(self, warning: Optional[_Warning], error_rows: List[dict]) -> None:
        self.warning = warning
        self.error_rows = error_rows
        self.queries: List[Any] = []
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle", username="APP"))
        self.log = SimpleNamespace(
            debug=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        )
        self._conn = create_engine("sqlite://").connect()

    def _ensure_connection(self):
        return self._conn

    def _ensure_schema_ready(self, schema=None):
        return None

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        return self.error_rows


@pytest.fixture
def run_unit(monkeypatch):
    def _run(provider: _Provider, sql: str) -> Any:
        def fake_execute(self, stmt, schema=None, params=None):
            conn = self._ensure_connection()
            conn.dispatch.after_cursor_execute(
                conn, _Cursor(provider.warning), stmt, (), None, False
            )
            return 0

        monkeypatch.setattr(
            "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute
        )
        return provider.execute_statement(sql)

    return _run


def test_cursor_warning_24344_fails_with_the_compile_errors_text(run_unit) -> None:
    provider = _Provider(
        _Warning("DPY-7000"),
        [
            {
                "line": 1,
                "position": 30,
                "text": "PLS-00201: identifier 'NO_SUCH_PROC' must be declared",
            }
        ],
    )

    with pytest.raises(ExecutionError) as caught:
        run_unit(provider, BAD_PROC)

    message = str(caught.value)
    assert "BAD_P" in message and "PLS-00201" in message and "line 1" in message


def test_user_errors_without_a_cursor_warning_still_fails(run_unit) -> None:
    provider = _Provider(None, [{"line": 2, "position": 3, "text": "PLS-00103: bad"}])

    with pytest.raises(ExecutionError, match="PLS-00103"):
        run_unit(provider, BAD_PROC)


def test_thick_mode_ora_24344_warning_fails_too(run_unit) -> None:
    provider = _Provider(_Warning("ORA-24344"), [])

    with pytest.raises(ExecutionError, match="ORA-24344"):
        run_unit(provider, BAD_PROC)


def test_warning_without_readable_errors_still_fails(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [])

    with pytest.raises(ExecutionError, match="ORA-24344"):
        run_unit(provider, BAD_PROC)


def test_valid_unit_succeeds(run_unit) -> None:
    provider = _Provider(None, [])

    assert run_unit(provider, BAD_PROC) == 0


def test_other_warning_codes_are_not_compile_errors(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7001"), [])

    assert run_unit(provider, BAD_PROC) == 0


def test_plain_ddl_is_not_checked(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [{"line": 1, "position": 1, "text": "x"}])

    assert run_unit(provider, "CREATE TABLE t (id NUMBER);") == 0
    assert provider.queries == []


def test_error_lookup_targets_the_unit_in_its_schema(run_unit) -> None:
    provider = _Provider(None, [])

    run_unit(provider, 'CREATE OR REPLACE PACKAGE BODY app."Pkg" AS END;')

    sql, params = provider.queries[0]
    assert "all_errors" in sql.lower()
    assert params == ["APP", "Pkg", "PACKAGE BODY"]
