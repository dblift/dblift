"""A PL/SQL unit Oracle compiles with errors (ORA-24344) fails the migration, at its end."""

from types import SimpleNamespace
from typing import Any, Callable, List, Optional

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
    """Provider whose driver cursor reports ``warning`` after every execute.

    ``lookup`` answers the dictionary query for a unit; ``on_execute`` sees every
    statement the provider sends to the database.
    """

    def __init__(
        self,
        warning: Optional[_Warning],
        error_rows: List[dict],
        lookup: Optional[Callable[[List[Any]], List[dict]]] = None,
        on_execute: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.warning = warning
        self.error_rows = error_rows
        self.lookup = lookup
        self.on_execute = on_execute
        self.queries: List[Any] = []
        self.executed: List[str] = []
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
        return self.lookup(params) if self.lookup else self.error_rows


def _invalid(text: str = "PLS-00201: identifier 'X' must be declared", line: int = 1) -> dict:
    return {"status": "INVALID", "line": line, "position": 30, "text": text}


VALID = [{"status": "VALID", "line": None, "position": None, "text": None}]


@pytest.fixture
def run_unit(monkeypatch):
    """Run the statements of one migration, then its end-of-migration check."""

    def _run(provider: _Provider, *statements: str) -> Any:
        def fake_execute(self, stmt, schema=None, params=None):
            conn = self._ensure_connection()
            provider.executed.append(stmt)
            if provider.on_execute:
                provider.on_execute(stmt)
            conn.dispatch.after_cursor_execute(
                conn, _Cursor(provider.warning), stmt, (), None, False
            )
            return 0

        monkeypatch.setattr(
            "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute
        )
        provider.reset_schema_cache()
        for statement in statements:
            provider.execute_statement(statement)
        return provider.finish_migration_statements()

    return _run


def test_cursor_warning_24344_fails_with_the_compile_errors_text(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])

    with pytest.raises(ExecutionError) as caught:
        run_unit(provider, BAD_PROC)

    message = str(caught.value)
    assert "BAD_P" in message and "PLS-00201" in message and "line 1" in message


def test_the_verdict_waits_for_the_end_of_the_migration(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])

    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC, "CREATE TABLE t (id NUMBER);")

    assert provider.executed[:2] == [BAD_PROC.rstrip(";") + ";", "CREATE TABLE t (id NUMBER)"]


def test_user_errors_without_a_cursor_warning_still_fails(run_unit) -> None:
    provider = _Provider(None, [_invalid("PLS-00103: bad", line=2)])

    with pytest.raises(ExecutionError, match="PLS-00103"):
        run_unit(provider, BAD_PROC)


def test_thick_mode_ora_24344_warning_fails_too(run_unit) -> None:
    provider = _Provider(_Warning("ORA-24344"), [{"status": "INVALID", "text": None}])

    with pytest.raises(ExecutionError, match="ORA-24344"):
        run_unit(provider, BAD_PROC)


def test_warning_with_an_invalid_unit_and_no_readable_errors_still_fails(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [{"status": "INVALID", "text": None}])

    with pytest.raises(ExecutionError, match="BAD_P: INVALID"):
        run_unit(provider, BAD_PROC)


def test_valid_unit_succeeds(run_unit) -> None:
    provider = _Provider(None, VALID)

    assert run_unit(provider, BAD_PROC) is None
    assert not [e for e in provider.executed if "COMPILE" in e]


def test_other_warning_codes_are_not_compile_errors(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7001"), VALID)

    assert run_unit(provider, BAD_PROC) is None


def test_plain_ddl_is_not_checked(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])

    assert run_unit(provider, "CREATE TABLE t (id NUMBER);") is None
    assert provider.queries == []


def test_error_lookup_targets_the_unit_in_its_schema(run_unit) -> None:
    provider = _Provider(None, VALID)

    run_unit(provider, 'CREATE OR REPLACE PACKAGE BODY app."Pkg" AS END;')

    sql, params = provider.queries[0]
    assert "all_errors" in sql.lower()
    assert params == ["APP", "Pkg", "PACKAGE BODY"]


# --- forward references: the unit is recompiled at the end of the migration -------------------------


def _forward_reference_db():
    """A database where recompiling ``a_p`` fixes it once ``b_p`` exists."""
    state = {"A_P": "INVALID", "B_P": "VALID"}

    def on_execute(stmt):
        if stmt.upper().startswith("ALTER PROCEDURE") and "A_P" in stmt:
            state["A_P"] = "VALID"

    def lookup(params):
        return VALID if state.get(params[1]) == "VALID" else [_invalid()]

    return on_execute, lookup


def test_a_unit_that_compiles_after_a_later_statement_succeeds(run_unit) -> None:
    on_execute, lookup = _forward_reference_db()
    provider = _Provider(_Warning("DPY-7000"), [], lookup=lookup, on_execute=on_execute)

    run_unit(
        provider,
        "CREATE OR REPLACE PROCEDURE a_p AS BEGIN b_p; END;",
        "CREATE OR REPLACE PROCEDURE b_p AS BEGIN NULL; END;",
    )

    assert 'ALTER PROCEDURE "A_P" COMPILE' in provider.executed


@pytest.mark.parametrize(
    ("create", "alter"),
    [
        ("CREATE OR REPLACE PACKAGE BODY app.pk AS END;", 'ALTER PACKAGE "APP"."PK" COMPILE BODY'),
        ("CREATE OR REPLACE TYPE BODY pk AS END;", 'ALTER TYPE "PK" COMPILE BODY'),
        ("CREATE OR REPLACE PACKAGE pk AS END;", 'ALTER PACKAGE "PK" COMPILE'),
        ("CREATE OR REPLACE TYPE pk AS OBJECT (x NUMBER);", 'ALTER TYPE "PK" COMPILE'),
        (
            "CREATE OR REPLACE TRIGGER pk BEFORE INSERT ON t BEGIN NULL; END;",
            'ALTER TRIGGER "PK" COMPILE',
        ),
        (
            "CREATE OR REPLACE FUNCTION pk RETURN NUMBER AS BEGIN RETURN 1; END;",
            'ALTER FUNCTION "PK" COMPILE',
        ),
    ],
)
def test_the_recompile_statement_matches_the_unit_type(run_unit, create, alter) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])

    with pytest.raises(ExecutionError):
        run_unit(provider, create)

    assert alter in provider.executed


def test_a_unit_that_stays_invalid_names_every_unit_with_its_first_error(run_unit) -> None:
    def lookup(params):
        first = _invalid(f"PLS-00201: {params[1]} first")
        return [first, _invalid("PLS-00999: second error", line=9)]

    provider = _Provider(_Warning("DPY-7000"), [], lookup=lookup)

    with pytest.raises(ExecutionError) as caught:
        run_unit(
            provider,
            "CREATE OR REPLACE PROCEDURE one_p AS BEGIN x; END;",
            "CREATE OR REPLACE PROCEDURE two_p AS BEGIN y; END;",
        )

    message = str(caught.value)
    assert len(message.splitlines()[0]) < 78
    assert "ORA-24344" in message.splitlines()[0]
    assert "ONE_P" in message and "TWO_P" in message
    assert "ONE_P first" in message and "TWO_P first" in message
    assert "PLS-00999" not in message


def test_a_replaced_unit_is_not_rechecked(run_unit) -> None:
    states = iter([[_invalid()], VALID])
    provider = _Provider(None, [], lookup=lambda params: next(states))

    run_unit(
        provider,
        "CREATE OR REPLACE PROCEDURE a_p AS BEGIN b_p; END;",
        "CREATE OR REPLACE PROCEDURE a_p AS BEGIN NULL; END;",
    )

    assert not [e for e in provider.executed if "COMPILE" in e]


def test_pending_units_do_not_leak_into_the_next_migration(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])
    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC)

    provider.executed.clear()
    provider.warning = None
    provider.error_rows = VALID

    assert run_unit(provider, "CREATE TABLE t (id NUMBER);") is None
    assert provider.executed == ["CREATE TABLE t (id NUMBER)"]


def test_reset_discards_units_left_by_a_failed_migration(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])
    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC)
    provider.execute_statement(BAD_PROC)  # a later migration failed before its end check
    provider.reset_schema_cache()

    assert provider.finish_migration_statements() is None


# --- ALTER ... COMPILE ----------------------------------------------------------------------------


def test_alter_compile_with_errors_fails(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid("PLS-00201: gone")])

    with pytest.raises(ExecutionError, match="PROCEDURE AC"):
        run_unit(provider, "ALTER PROCEDURE ac COMPILE;")


def test_alter_compile_that_fixes_the_unit_succeeds(run_unit) -> None:
    provider = _Provider(None, VALID)

    assert run_unit(provider, "ALTER PROCEDURE ac COMPILE;") is None
    assert provider.queries[0][1] == [None, "AC", "PROCEDURE"]


@pytest.mark.parametrize(
    ("statement", "types"),
    [
        ("ALTER PACKAGE app.pk COMPILE BODY", ["PACKAGE BODY"]),
        ("ALTER PACKAGE pk COMPILE SPECIFICATION", ["PACKAGE"]),
        ("ALTER PACKAGE pk COMPILE", ["PACKAGE", "PACKAGE BODY"]),
        ("ALTER TYPE pk COMPILE BODY", ["TYPE BODY"]),
        ("ALTER VIEW v COMPILE", ["VIEW"]),
        ("ALTER TRIGGER trg COMPILE DEBUG", ["TRIGGER"]),
        ("ALTER FUNCTION f COMPILE REUSE SETTINGS", ["FUNCTION"]),
    ],
)
def test_alter_compile_forms_are_recognised(run_unit, statement, types) -> None:
    provider = _Provider(None, VALID)

    run_unit(provider, statement)

    assert [params[2] for _sql, params in provider.queries] == types


def test_other_alter_statements_are_not_checked(run_unit) -> None:
    provider = _Provider(_Warning("DPY-7000"), [_invalid()])

    assert run_unit(provider, "ALTER TABLE t ADD (c NUMBER);") is None
    assert provider.queries == []
