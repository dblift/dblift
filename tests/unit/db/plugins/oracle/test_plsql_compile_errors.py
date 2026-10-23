"""A PL/SQL unit left INVALID (ORA-24344 and its kin) fails the migration, at its end."""

from types import SimpleNamespace
from typing import Any, Callable, List, Optional

import pytest

from dblift.core.exceptions import ExecutionError
from dblift.db.plugins.oracle.provider import OracleProvider

BAD_PROC = "CREATE OR REPLACE PROCEDURE bad_p AS BEGIN no_such_proc(1); END;"


class _Provider(OracleProvider):
    """Provider whose dictionary answers ``lookup`` and that records what it executes."""

    def __init__(
        self,
        rows: List[dict],
        lookup: Optional[Callable[[List[Any]], List[dict]]] = None,
        on_execute: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.rows = rows
        self.lookup = lookup
        self.on_execute = on_execute
        self.queries: List[Any] = []
        self.executed: List[str] = []
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle", username="APP"))
        self.log = SimpleNamespace(
            debug=lambda *a, **k: None, warning=lambda *a, **k: None, error=lambda *a, **k: None
        )

    def _ensure_schema_ready(self, schema=None):
        return None

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        return self.lookup(params) if self.lookup else self.rows


def _invalid(text: str = "PLS-00201: identifier 'X' must be declared", line: int = 1) -> dict:
    return {"status": "INVALID", "line": line, "position": 30, "text": text}


VALID = [{"status": "VALID", "line": None, "position": None, "text": None}]


@pytest.fixture
def run_unit(monkeypatch):
    """Run the statements of one migration, then its end-of-migration check."""

    def _run(provider: _Provider, *statements: str) -> Any:
        def fake_execute(self, stmt, schema=None, params=None):
            provider.executed.append(stmt)
            if provider.on_execute:
                provider.on_execute(stmt)
            return 0

        monkeypatch.setattr(
            "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute
        )
        provider.reset_schema_cache()
        for statement in statements:
            provider.execute_statement(statement)
        return provider.finish_migration_statements(list(statements))

    return _run


def _recompiles(provider: _Provider) -> List[str]:
    return [e for e in provider.executed if "COMPILE" in e]


def test_an_invalid_unit_fails_with_the_compile_errors_text(run_unit) -> None:
    provider = _Provider([_invalid()])

    with pytest.raises(ExecutionError) as caught:
        run_unit(provider, BAD_PROC)

    message = str(caught.value)
    assert "BAD_P" in message and "PLS-00201" in message and "line 1" in message


def test_the_verdict_waits_for_the_end_of_the_migration(run_unit) -> None:
    provider = _Provider([_invalid()])

    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC, "CREATE TABLE t (id NUMBER);")

    assert provider.executed[:2] == [BAD_PROC.rstrip(";") + ";", "CREATE TABLE t (id NUMBER)"]


def test_an_invalid_unit_with_no_readable_errors_still_fails(run_unit) -> None:
    provider = _Provider([{"status": "INVALID", "text": None}])

    with pytest.raises(ExecutionError, match="BAD_P: INVALID"):
        run_unit(provider, BAD_PROC)


def test_a_valid_unit_succeeds_without_a_recompile(run_unit) -> None:
    provider = _Provider(VALID)

    assert run_unit(provider, BAD_PROC) is None
    assert _recompiles(provider) == []


def test_plain_ddl_is_not_tracked(run_unit) -> None:
    provider = _Provider([_invalid()])

    assert run_unit(provider, "CREATE TABLE t (id NUMBER);") is None
    assert provider.queries == []


def test_a_unit_gone_by_the_end_is_not_judged(run_unit) -> None:
    provider = _Provider([])

    assert run_unit(provider, BAD_PROC) is None
    assert _recompiles(provider) == []


def test_the_lookup_targets_the_unit_in_its_schema(run_unit) -> None:
    provider = _Provider(VALID)

    run_unit(provider, 'CREATE OR REPLACE PACKAGE BODY app."Pkg" AS END;')

    sql, params = provider.queries[0]
    assert "all_errors" in sql.lower()
    assert params == ["APP", "Pkg", "PACKAGE BODY"]


def _forward_reference_db():
    """A database where recompiling ``a_p`` fixes it once ``b_p`` exists."""
    state = {"A_P": "INVALID", "B_P": "VALID"}

    def on_execute(stmt):
        if "ALTER PROCEDURE" in stmt and "A_P" in stmt:
            state["A_P"] = "VALID"

    def lookup(params):
        return VALID if state.get(params[1]) == "VALID" else [_invalid()]

    return on_execute, lookup


def test_a_unit_that_compiles_after_a_later_statement_succeeds(run_unit) -> None:
    on_execute, lookup = _forward_reference_db()
    provider = _Provider([], lookup=lookup, on_execute=on_execute)

    run_unit(
        provider,
        "CREATE OR REPLACE PROCEDURE a_p AS BEGIN b_p; END;",
        "CREATE OR REPLACE PROCEDURE b_p AS BEGIN NULL; END;",
    )

    assert any('ALTER PROCEDURE "A_P" COMPILE' in e for e in provider.executed)
    assert not any('"B_P"' in e for e in _recompiles(provider))


def test_a_unit_invalidated_after_its_create_is_recompiled(run_unit) -> None:
    on_execute, lookup = _forward_reference_db()
    provider = _Provider([], lookup=lookup, on_execute=on_execute)

    run_unit(
        provider,
        "CREATE OR REPLACE PROCEDURE b_p AS BEGIN NULL; END;",
        "CREATE OR REPLACE PROCEDURE a_p AS BEGIN b_p; END;",
        "ALTER TABLE e DROP COLUMN c;",
    )

    assert any('"A_P"' in e for e in _recompiles(provider))


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
        ("CREATE OR REPLACE FORCE VIEW pk AS SELECT * FROM missing", 'ALTER VIEW "PK" COMPILE'),
    ],
)
def test_the_recompile_statement_matches_the_unit_type(run_unit, create, alter) -> None:
    provider = _Provider([_invalid()])

    with pytest.raises(ExecutionError):
        run_unit(provider, create)

    assert any(alter in e for e in provider.executed)


def test_a_recompile_cannot_commit_the_migration_transaction(run_unit) -> None:
    provider = _Provider([_invalid()])

    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC)

    (recompile,) = _recompiles(provider)
    assert "PRAGMA AUTONOMOUS_TRANSACTION" in recompile
    assert recompile.startswith("DECLARE")


@pytest.mark.parametrize(
    ("statement", "judged"),
    [
        ("CREATE OR REPLACE FORCE VIEW v AS SELECT * FROM missing", True),
        ("CREATE OR REPLACE EDITIONABLE FORCE VIEW v AS SELECT 1 FROM dual", True),
        ("CREATE OR REPLACE NO FORCE VIEW v AS SELECT 1 FROM dual", False),
        ("CREATE VIEW v AS SELECT 1 FROM dual", False),
        ("CREATE OR REPLACE FORCE EDITIONABLE VIEW v AS SELECT 1 FROM dual", True),
    ],
)
def test_only_force_views_are_tracked(run_unit, statement, judged) -> None:
    provider = _Provider(VALID)

    run_unit(provider, statement)

    assert bool(provider.queries) is judged
    if judged:
        assert provider.queries[0][1] == [None, "V", "VIEW"]


def test_a_force_view_over_a_missing_table_fails_naming_the_view(run_unit) -> None:
    provider = _Provider([_invalid("ORA-00942: table or view does not exist")])

    with pytest.raises(ExecutionError, match="VIEW V"):
        run_unit(provider, "CREATE OR REPLACE FORCE VIEW v AS SELECT * FROM missing")


def test_every_still_invalid_unit_is_listed_with_its_first_error(run_unit) -> None:
    def lookup(params):
        return [_invalid(f"PLS-00201: {params[1]} first"), _invalid("PLS-00999: second", line=9)]

    provider = _Provider([], lookup=lookup)

    with pytest.raises(ExecutionError) as caught:
        run_unit(
            provider,
            "CREATE OR REPLACE PROCEDURE one_p AS BEGIN x; END;",
            "CREATE OR REPLACE PROCEDURE two_p AS BEGIN y; END;",
        )

    message = str(caught.value)
    assert len(message.splitlines()[0]) < 78
    assert "ORA-24344" in message.splitlines()[0]
    assert "ONE_P first" in message and "TWO_P first" in message
    assert "PLS-00999" not in message


def test_the_failure_names_the_statement_that_made_the_first_invalid_unit(run_unit) -> None:
    def lookup(params):
        return [_invalid()] if params[1] == "BAD_P" else VALID

    provider = _Provider([], lookup=lookup)

    with pytest.raises(ExecutionError) as caught:
        run_unit(
            provider,
            "CREATE TABLE t (id NUMBER);",
            "CREATE OR REPLACE PROCEDURE good_p AS BEGIN NULL; END;",
            BAD_PROC,
            "INSERT INTO t VALUES (1);",
        )

    assert caught.value.statement_index == 2


def test_a_unit_created_twice_is_judged_once(run_unit) -> None:
    provider = _Provider(VALID)

    run_unit(provider, BAD_PROC, BAD_PROC)

    assert len(provider.queries) == 1


def test_pending_units_do_not_leak_into_the_next_migration(run_unit) -> None:
    provider = _Provider([_invalid()])
    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC)

    provider.executed.clear()
    provider.rows = VALID

    assert run_unit(provider, "CREATE TABLE t (id NUMBER);") is None
    assert provider.executed == ["CREATE TABLE t (id NUMBER)"]


def test_reset_discards_units_left_by_a_failed_migration(run_unit) -> None:
    provider = _Provider([_invalid()])
    with pytest.raises(ExecutionError):
        run_unit(provider, BAD_PROC)
    provider.execute_statement(BAD_PROC)  # a later migration failed before its end check
    provider.reset_schema_cache()

    assert provider.finish_migration_statements([]) is None


def test_alter_compile_with_errors_fails(run_unit) -> None:
    provider = _Provider([_invalid("PLS-00201: gone")])

    with pytest.raises(ExecutionError, match="PROCEDURE AC"):
        run_unit(provider, "ALTER PROCEDURE ac COMPILE;")


def test_alter_compile_that_fixes_the_unit_succeeds(run_unit) -> None:
    provider = _Provider(VALID)

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
    provider = _Provider(VALID)

    run_unit(provider, statement)

    assert [params[2] for _sql, params in provider.queries] == types


def test_other_alter_statements_are_not_tracked(run_unit) -> None:
    provider = _Provider([_invalid()])

    assert run_unit(provider, "ALTER TABLE t ADD (c NUMBER);") is None
    assert provider.queries == []
