"""The engine sends the list the splitter returned and decides nothing about it."""

from __future__ import annotations

import ast
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from tests.support.transaction_scenarios import database_url, read_state
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
SRC = REPO / "dblift"
FILTERS = {
    "strip",
    "is_comment_only_statement",
    "_is_comment_only_statement",
    "_comment_only",
    "_is_empty_or_comment",
    "is_batch_separator",
}


def _engine(dialect: str) -> ExecutionEngine:
    provider = MagicMock()
    provider.connection = None
    provider.execute_statement.return_value = 0
    log = MagicMock()
    return ExecutionEngine(provider, SqlAnalyzer(dialect=dialect, logger=log), log)


# --- no filter is left on a statement ------------------------------------------------------------


def _filter_calls(path: Path, functions: set) -> list:
    """``(function, name)`` of every filter inside the named functions of *path*.

    A ``strip`` whose result is only read on (``statement.strip().upper()``) is no filter; one
    used as a value (``stripped = statement.strip(blanks)``) is.
    """
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not (isinstance(node, ast.FunctionDef) and node.name in functions):
            continue
        parents = {
            child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)
        }
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            chained = isinstance(parents.get(call), ast.Attribute)
            if name in FILTERS and not (name == "strip" and chained):
                found.append((node.name, name))
    return found


ENGINE_LOOPS = {
    "_classify_execution_statements",
    "get_executable_sql_statements",
    "_execute_statements",
    "execute_callback",
}


def test_no_loop_of_the_engine_filters_a_statement():
    path = SRC / "core/migration/executor/execution_engine.py"
    assert _filter_calls(path, ENGINE_LOOPS) == []


def test_execute_statement_filters_nothing():
    path = SRC / "core/migration/sql/sql_execution_service.py"
    assert _filter_calls(path, {"execute_statement"}) == []


# The analysis path reads the splitter's list too: a skip planted in one of these loops is
# caught here, not only by the parity matrix.
ANALYSIS_LOOPS = [
    ("core/migration/sql/script_analysis.py", {"_analyse"}),
    ("core/migration/sql/lint_rules.py", {"_mixed_transaction_modes", "issues_and_created_tables"}),
    ("core/sql_parser/statement_facts_parser.py", {"parse_sql"}),
]


@pytest.mark.parametrize("relative, functions", ANALYSIS_LOOPS)
def test_no_loop_of_the_analysis_path_filters_a_statement(relative, functions):
    assert _filter_calls(SRC / relative, functions) == []


def test_the_scan_sees_a_planted_filter(tmp_path):
    planted = tmp_path / "engine.py"
    planted.write_text("def _execute_statements(s):\n    return [x for x in s if x.strip()]\n")
    assert _filter_calls(planted, ENGINE_LOOPS) == [("_execute_statements", "strip")]


# --- what the engine sends ----------------------------------------------------------------------


def test_a_callback_sends_a_statement_of_a_character_the_engine_rejects():
    engine = _engine("sqlite")
    callback = make_migration(
        script_name="beforeMigrate__x.sql",
        content="CREATE TABLE a (x INT);\n\x1c;\nCREATE TABLE b (y INT);",
        logger=engine.log,
    )
    engine.execute_callback(callback)
    sent = [call.args[0] for call in engine.provider.execute_statement.call_args_list]
    assert sent == ["CREATE TABLE a (x INT)", "\x1c", "CREATE TABLE b (y INT)"]


def test_duckdb_sends_the_statement_after_a_comment_ended_by_a_carriage_return():
    engine = _engine("duckdb")
    migration = make_migration(
        script_name="V1__x.sql", content="SELECT 1; -- c\rSELECT 2;", logger=engine.log
    )
    assert engine.get_executable_sql_statements(migration, MagicMock()) == [
        "SELECT 1",
        "-- c\rSELECT 2",
    ]


def test_prepare_logs_the_go_0_notice_once(caplog):
    engine = _engine("sqlserver")
    migration = make_migration(
        script_name="V1__x.sql", content="SELECT 1\nGO 0\nSELECT 2", logger=engine.log
    )
    with caplog.at_level(logging.INFO):
        sent = engine._prepare_sql_statements(migration)
    assert sent == ["SELECT 2"]
    assert len([r for r in caplog.records if "GO 0 follows" in r.getMessage()]) == 1


# --- a failing statement of kept characters rolls the migration back, on the real engines --------


def _migrate(engine_name: str, directory: Path, script: str) -> subprocess.CompletedProcess:
    migrations = directory / "m"
    migrations.mkdir()
    (migrations / "V1__x.sql").write_text(script, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(REPO), NO_COLOR="1", COLUMNS="200", HOME=str(directory))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--db-url",
            database_url(engine_name, directory),
            "--scripts",
            str(migrations),
            "migrate",
        ],
        capture_output=True,
        text=True,
        cwd=directory,
        env=env,
        timeout=120,
    )


@pytest.mark.parametrize(
    "engine_name, piece", [("sqlite", "\xa0"), ("sqlite", "\x1c"), ("duckdb", "\x1c")]
)
def test_a_statement_the_engine_rejects_fails_the_migration_and_leaves_nothing(
    engine_name, piece, tmp_path
):
    script = f"CREATE TABLE ta (a INT);\n{piece};\nCREATE TABLE tb (a INT);\n"
    proc = _migrate(engine_name, tmp_path, script)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    tables, history = read_state(engine_name, tmp_path)
    assert tables == {}
    assert ("V1__x.sql", True) not in history
