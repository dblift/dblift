"""Exercise an intentionally incomplete installed dependency profile."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=Path.cwd(), capture_output=True, text=True, timeout=120)


def _presentation() -> bool:
    work = Path.cwd()
    before = {path.relative_to(work) for path in work.rglob("*") if path.is_file()}
    assert importlib.util.find_spec("rich") is None
    assert importlib.util.find_spec("jinja2") is None
    import dblift
    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog

    origin = Path(dblift.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert "/site-packages/dblift/" in str(origin)
    migrations = Path.cwd() / "diagnostic_migrations"
    migrations.mkdir()
    (migrations / "V1__create.sql").write_text(
        "CREATE TABLE no_presentation (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO no_presentation VALUES (7);\n",
        encoding="utf-8",
    )
    (migrations / "U1__create.sql").write_text("DROP TABLE no_presentation;\n", encoding="utf-8")
    database = Path.cwd() / "diagnostic.sqlite"
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(database), "schema": "main"}}
    )
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with DBLiftClient.from_config(
            config, migrations_dir=migrations, logger=NullLog()
        ) as client:
            assert client.migrate().success
            assert client.info().success
            assert client.validate().success
            assert client.undo(target_version="0.0.0").success
    assert out.getvalue() == err.getvalue() == ""
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='no_presentation'"
            ).fetchall()
            == []
        )
    added = {path.relative_to(work) for path in work.rglob("*") if path.is_file()} - before
    expected = {
        Path("diagnostic_migrations/V1__create.sql"),
        Path("diagnostic_migrations/U1__create.sql"),
        Path("diagnostic.sqlite"),
    }
    assert added == expected, added
    return True


def _sqlglot() -> dict:
    assert importlib.util.find_spec("sqlglot") is None
    from dblift.api import DBLiftClient
    from dblift.config import DbliftConfig
    from dblift.core.logger import NullLog
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
    from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
    from dblift.db.plugins.sqlite.provider import SQLiteProvider

    config = DbliftConfig.from_dict({"database": {"type": "sqlite", "url": "sqlite:///:memory:"}})
    provider = SQLiteProvider(config, NullLog())
    provider.create_connection()
    try:
        service = SqlExecutionService(provider, SqlAnalyzer("sqlite"), journal=None)
        assert service.execute_statement("CREATE TABLE t (id INTEGER)")[0] is False
        assert service.execute_statement("INSERT INTO t VALUES (?)", params=[7])[0] is False
        is_query, rows = service.execute_statement("SELECT id FROM t WHERE id = ?", params=[7])
        assert is_query and rows == [{"id": 7}]
        assert service.execute_statement("DROP TABLE t")[0] is False
        assert provider.execute_query("SELECT name FROM sqlite_master WHERE name='t'") == []
    finally:
        provider.close()

    migrations = Path.cwd() / "sqlglot_migrations"
    migrations.mkdir()
    (migrations / "V1__create.sql").write_text(
        "CREATE TABLE standard_client_target (id INTEGER);\n", encoding="utf-8"
    )
    database = Path.cwd() / "sqlglot_standard.sqlite"
    standard_config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(database), "schema": "main"}}
    )
    failure = ""
    try:
        with DBLiftClient.from_config(
            standard_config, migrations_dir=migrations, logger=NullLog()
        ) as client:
            result = client.migrate()
            assert not result.success
            failure = result.error_message or ""
            assert "sqlglot" in failure.lower(), failure
    except ModuleNotFoundError as exc:
        assert exc.name == "sqlglot", exc.name
        failure = f"ModuleNotFoundError: {exc.name}"
    with sqlite3.connect(database) as connection:
        objects = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
    assert objects == []
    (migrations / "R__seed.sql").write_text(
        "INSERT INTO standard_client_target VALUES (9);\n", encoding="utf-8"
    )
    (migrations / "U1__create.sql").write_text(
        "DROP TABLE standard_client_target;\n", encoding="utf-8"
    )
    with DBLiftClient.from_config(
        standard_config, migrations_dir=migrations, logger=NullLog(), analysis_mode="execution"
    ) as client:
        migrated = client.migrate()
        assert migrated.success, migrated.error_message
        assert migrated.journal.capture_objects is False
        assert client.provider.execute_query("SELECT * FROM standard_client_target") == [{"id": 9}]
        assert client.validate().success
        assert client.undo(target_version="0.0.0").success
    return {"failure": failure, "tables_after_failure": objects, "execution_cycle": True}


def main() -> None:
    profile = os.environ.get("DBLIFT_E4_DIAGNOSTIC_PROFILE")
    if profile not in {"presentation", "sqlglot"}:
        raise ValueError(f"Unsupported diagnostic profile: {profile}")
    venv = Path(sys.prefix).resolve()
    assert venv != Path(sys.base_prefix).resolve()
    installed_spec = importlib.util.find_spec("dblift")
    assert installed_spec is not None and installed_spec.origin is not None
    assert Path(installed_spec.origin).resolve().is_relative_to(venv)
    removed = ["Jinja2", "rich"] if profile == "presentation" else ["sqlglot"]
    uninstall = _run([sys.executable, "-m", "pip", "uninstall", "-y", *removed])
    assert uninstall.returncode == 0
    pip_check = _run([sys.executable, "-m", "pip", "check"])
    assert pip_check.returncode != 0
    sqlglot_evidence = None
    if profile == "presentation":
        presentation_verified = _presentation()
    else:
        presentation_verified = False
        sqlglot_evidence = _sqlglot()
    import dblift

    print(
        json.dumps(
            {
                "status": "pass",
                "origin": str(Path(dblift.__file__).resolve()),
                "workdir": str(Path.cwd().resolve()),
                "profile": profile,
                "missing": removed,
                "venv_verified_before_uninstall": True,
                "pip_check_returncode": pip_check.returncode,
                "pip_check_output": pip_check.stdout + pip_check.stderr,
                "silent_sqlite": profile == "presentation",
                "no_implicit_report_files": presentation_verified,
                "low_level_v_u": profile == "sqlglot",
                "standard_client_failed_before_mutation": profile == "sqlglot",
                "standard_client_failure": sqlglot_evidence,
                "execution_cycle": bool(sqlglot_evidence and sqlglot_evidence["execution_cycle"]),
            }
        )
    )


if __name__ == "__main__":
    main()
