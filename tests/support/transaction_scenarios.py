"""Scripts with transaction statements, and the state a migration of each must leave.

One table drives the in-process ``from_sqlalchemy`` tests and the CLI subprocess tests, so
the two connection paths are held to the same outcomes. ``tables`` is what the migration
leaves behind (table -> column ``a`` values), ``history`` the ``(script, success)`` rows.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ENGINES = ("sqlite", "duckdb")
SCRIPT = "V1__x.sql"
Row = Tuple[str, bool]


@dataclass(frozen=True)
class Scenario:
    script: str
    status: (
        str  # "applied" | "failed" (ran, rolled back, failure recorded) | "refused" (nothing ran)
    )
    tables: Dict[str, List[int]]
    history: Optional[List[Row]] = None  # default: the row implied by ``status``
    engines: Tuple[str, ...] = ENGINES
    message: Optional[str] = None  # text the refusal / failure must carry

    def expected_history(self) -> List[Row]:
        if self.history is not None:
            return self.history
        return {"applied": [(SCRIPT, True)], "failed": [(SCRIPT, False)], "refused": []}[
            self.status
        ]


T1 = {"t": [1]}
SCENARIOS: Dict[str, Scenario] = {
    "envelope": Scenario(
        "BEGIN;\nCREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\nCOMMIT;\n", "applied", T1
    ),
    "envelope_words_lowercase": Scenario(
        "begin transaction;\ncreate table t(a int);\ninsert into t values (1);\nend transaction;\n",
        "applied",
        T1,
    ),
    "envelope_comments_around": Scenario(
        "-- header\nBEGIN;\n-- body\nCREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\nCOMMIT; -- done\n",
        "applied",
        T1,
    ),
    "envelope_failing_body": Scenario(
        "BEGIN;\nCREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\nSELECT * FROM nosuch;\nCOMMIT;\n",
        "failed",
        {},
    ),
    "trigger_body_begin_end": Scenario(
        "CREATE TABLE t(a INT);\n"
        "CREATE TRIGGER tg AFTER INSERT ON t BEGIN INSERT INTO t VALUES (9); END;\n",
        "applied",
        {"t": []},
        engines=("sqlite",),
    ),
    "lone_commit": Scenario("COMMIT;\n", "refused", {}, message="line 1"),
    "commit_mid_then_error": Scenario(
        "CREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\nCOMMIT;\nINSERT INTO t VALUES (2);\n"
        "SELECT * FROM nosuch;\n",
        "refused",
        {},
        message="line 3",
    ),
    "end_mid": Scenario(
        "CREATE TABLE t(a INT);\nEND;\nINSERT INTO t VALUES (1);\n", "refused", {}, message="line 2"
    ),
    "rollback_mid": Scenario(
        "CREATE TABLE t(a INT);\nROLLBACK;\nCREATE TABLE u(a INT);\n",
        "refused",
        {},
        message="line 2",
    ),
    "begin_mid": Scenario(
        "CREATE TABLE t(a INT);\nBEGIN;\nINSERT INTO t VALUES (1);\nCOMMIT;\n",
        "refused",
        {},
        message="line 2",
    ),
    "envelope_closed_by_rollback": Scenario(
        "BEGIN;\nCREATE TABLE t(a INT);\nROLLBACK;\n", "refused", {}, message="line 3"
    ),
    "unterminated_begin": Scenario(
        "CREATE TABLE t(a INT);\nBEGIN;\nINSERT INTO t VALUES (1);\n",
        "refused",
        {},
        message="line 2",
    ),
    "two_envelopes": Scenario(
        "BEGIN;\nCREATE TABLE t(a INT);\nCOMMIT;\nBEGIN;\nCREATE TABLE u(a INT);\nCOMMIT;\n",
        "refused",
        {},
        message="line 3",
    ),
    "abort_closing_envelope": Scenario(
        "BEGIN;\nCREATE TABLE t(a INT);\nABORT;\n",
        "refused",
        {},
        engines=("duckdb",),
        message="line 3",
    ),
    "begin_exclusive_is_not_the_envelope": Scenario(
        "BEGIN EXCLUSIVE;\nCREATE TABLE t(a INT);\nCOMMIT;\n",
        "refused",
        {},
        engines=("sqlite",),
        message="line 3",
    ),
    "start_transaction_envelope": Scenario(
        "START TRANSACTION;\nCREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\nCOMMIT;\n",
        "applied",
        T1,
        engines=("duckdb",),
    ),
    "savepoint_release": Scenario(
        "CREATE TABLE t(a INT);\nSAVEPOINT s;\nINSERT INTO t VALUES (1);\nRELEASE s;\n",
        "applied",
        T1,
        engines=("sqlite",),
    ),
    "savepoint_rollback_to": Scenario(
        "CREATE TABLE t(a INT);\nSAVEPOINT s;\nINSERT INTO t VALUES (1);\nROLLBACK TO s;\n"
        "INSERT INTO t VALUES (2);\n",
        "applied",
        {"t": [2]},
        engines=("sqlite",),
    ),
    "savepoint_unsupported_by_engine": Scenario(
        "CREATE TABLE t(a INT);\nSAVEPOINT s;\n", "failed", {}, engines=("duckdb",)
    ),
    "vacuum_alone": Scenario("VACUUM;\n", "applied", {}),
    "vacuum_after_ddl": Scenario(
        "CREATE TABLE t(a INT);\nVACUUM;\n", "refused", {}, engines=("sqlite",), message="VACUUM"
    ),
}


def cases() -> List[Tuple[str, str]]:
    return [(engine, name) for name, s in SCENARIOS.items() for engine in s.engines]


def database_url(engine: str, directory: Path) -> str:
    return (
        f"sqlite:///{directory / 'a.db'}"
        if engine == "sqlite"
        else f"duckdb:///{directory / 'a.duckdb'}"
    )


def read_state(engine: str, directory: Path) -> Tuple[Dict[str, List[int]], List[Row]]:
    """Tables (other than dblift's) and history rows of the file database, read with the engine's driver."""
    if engine == "sqlite":
        conn = sqlite3.connect(directory / "a.db")
        fetch = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        names = "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
    else:
        import duckdb

        conn = duckdb.connect(str(directory / "a.duckdb"), read_only=True)
        fetch = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        names = "select table_name from information_schema.tables where table_schema='main'"
    try:
        all_tables = [r[0] for r in fetch(names)]
        tables = {
            t: sorted(r[0] for r in fetch(f"select a from {t}"))
            for t in all_tables
            if not t.startswith("dblift")
        }
        history = (
            [
                (r[0], bool(r[1]))
                for r in fetch(
                    "select script, success from dblift_schema_history order by installed_rank"
                )
            ]
            if "dblift_schema_history" in all_tables
            else []
        )
        return tables, history
    finally:
        conn.close()
