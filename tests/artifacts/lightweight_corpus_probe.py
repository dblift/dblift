"""Standalone SQLite corpus executed from an installed DBLift wheel."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.abc
import importlib.util
import io
import json
import runpy
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import time
from pathlib import Path


class _RemovedProviderBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        if len(parts) >= 4 and parts[:3] == ["dblift", "db", "plugins"]:
            if parts[3] in REMOVED:
                raise ModuleNotFoundError(f"Removed provider imported: {fullname}")
        return None


if len(sys.argv) > 1 and sys.argv[1] == "--cli":
    REMOVED = set(json.loads(sys.argv[2]))
elif len(sys.argv) > 1 and sys.argv[1] == "--concurrent-worker":
    REMOVED = set(json.loads(sys.argv[6]))
else:
    REMOVED = set(json.loads(sys.argv[2])) if len(sys.argv) > 2 else set()
if REMOVED:
    sys.meta_path.insert(0, _RemovedProviderBlocker())

import dblift
from dblift.api import DBLiftClient
from dblift.api.async_client import AsyncDBLiftClient
from dblift.config import DbliftConfig
from dblift.core.constants import DEFAULT_HISTORY_TABLE, MIGRATION_LOCK_TABLE
from dblift.core.logger import NullLog


def _client(database: Path, migrations: Path) -> DBLiftClient:
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(database), "schema": "main"}}
    )
    return DBLiftClient.from_config(config, migrations_dir=migrations, logger=NullLog())


def _rows(database: Path, query: str) -> list[list]:
    with sqlite3.connect(database) as connection:
        return [list(row) for row in connection.execute(query)]


def _history(database: Path) -> list[list]:
    return _rows(
        database,
        f'SELECT script, version, type, checksum, success FROM "{DEFAULT_HISTORY_TABLE}" '
        "ORDER BY installed_rank",
    )


def _scripts(result) -> list[list[str]]:
    return [[item.script, item.status] for item in result.migrations]


def _sql(result) -> list[list]:
    return [[item.script, item.statements] for item in result.sql]


def _core(work: Path) -> dict:
    migrations = work / "core"
    shutil.copytree(work / "fixtures" / "core", migrations)
    database = work / "core.sqlite"
    repeatable = migrations / "R__item_view.sql"
    versioned = migrations / "V1__items.sql"
    with _client(database, migrations) as client:
        first = client.migrate(placeholders={"seed_value": "fixture-seed"}, show_sql=True)
        assert first.success, first.error_message
        assert _rows(database, "SELECT id, value FROM items") == [[1, "fixture-seed"]]
        assert _rows(database, "SELECT id, item_id FROM notes") == [[1, 1]]
        assert _rows(database, "SELECT id, value FROM item_view") == [[1, "fixture-seed"]]
        first_history = _history(database)
        first_callbacks = _rows(database, "SELECT event FROM callback_log ORDER BY id")
        assert first_callbacks[0] == ["beforeMigrate"]
        assert first_callbacks[-1] == ["afterMigrate"]
        assert client.info().success
        assert client.validate().success
        unchanged = client.migrate(placeholders={"seed_value": "fixture-seed"})
        assert unchanged.success and not unchanged.migrations
        assert _history(database) == first_history
        repeatable.write_text(
            repeatable.read_text(encoding="utf-8") + "\n-- repeatable checksum changed\n",
            encoding="utf-8",
        )
        changed = client.migrate(placeholders={"seed_value": "fixture-seed"})
        assert changed.success, changed.error_message
        assert [item.script for item in changed.migrations] == ["R__item_view.sql"]
        callbacks_after_repeatable = _rows(database, "SELECT event FROM callback_log ORDER BY id")
        versioned_original = versioned.read_text(encoding="utf-8")
        versioned.write_text(versioned_original + "\n-- checksum changed\n", encoding="utf-8")
        drift = client.validate()
        assert not drift.success
        versioned.write_text(versioned_original, encoding="utf-8")
        restored = client.validate()
        assert restored.success
        before_undo = _history(database)
        undo = client.undo(target_version="0.0.0", show_sql=True)
        assert undo.success, undo.error_message
        assert [item.script for item in undo.migrations] == ["U2__notes.sql", "U1__items.sql"]
        final_info = client.info()
        assert final_info.success
        assert final_info.current_schema_version is None
        final_history = _history(database)
        assert final_history
    remaining_tables = _rows(
        database,
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('items', 'notes')",
    )
    assert remaining_tables == []
    assert _rows(database, "SELECT name FROM sqlite_master WHERE name='item_view'") == []
    return {
        "first_migrations": _scripts(first),
        "first_sql": _sql(first),
        "first_history": first_history,
        "callbacks": first_callbacks,
        "callbacks_after_repeatable": callbacks_after_repeatable,
        "repeatable_rerun": _scripts(changed),
        "history_before_undo": before_undo,
        "drift_issue_count": len(drift.issues),
        "undo_migrations": _scripts(undo),
        "undo_sql": _sql(undo),
        "final_info_version": final_info.current_schema_version,
        "final_info_migrations": _scripts(final_info),
        "final_history": final_history,
        "remaining_tables": remaining_tables,
    }


def _invalid(work: Path) -> dict:
    migrations = work / "invalid"
    shutil.copytree(work / "fixtures" / "invalid", migrations)
    database = work / "invalid.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE rollback_marker (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO rollback_marker VALUES (1, 'original')")
    with _client(database, migrations) as client:
        failed = client.migrate(show_sql=True)
        assert not failed.success
        assert "missing_table" in (failed.error_message or "")
        after_failure = _history(database)
        prior_write_rolled_back = _rows(
            database, "SELECT value FROM rollback_marker WHERE id = 1"
        ) == [["original"]]
        assert prior_write_rolled_back
        assert not _rows(database, "SELECT name FROM sqlite_master WHERE name='missing_table'")
        sentinel_exists = bool(
            _rows(database, "SELECT name FROM sqlite_master WHERE name='sentinel'")
        )
        sentinel_rows = _rows(database, "SELECT * FROM sentinel") if sentinel_exists else []
        assert sentinel_rows == []
        lock_rows = _rows(database, f'SELECT * FROM "{MIGRATION_LOCK_TABLE}"')
        assert lock_rows == []
        script = migrations / "V1__invalid.sql"
        script.write_text(
            "CREATE TABLE IF NOT EXISTS sentinel (id INTEGER PRIMARY KEY, value TEXT);\n"
            "UPDATE rollback_marker SET value = 'repaired' WHERE id = 1;\n"
            "INSERT INTO sentinel (id, value) VALUES (1, 'repaired');\n",
            encoding="utf-8",
        )
        repaired = client.repair()
        assert repaired.success, repaired.error_message
        retried = client.migrate()
        assert retried.success, retried.error_message
    assert _rows(database, "SELECT id, value FROM sentinel") == [[1, "repaired"]]
    assert _rows(database, "SELECT value FROM rollback_marker WHERE id = 1") == [["repaired"]]
    return {
        "failed_migrations": _scripts(failed),
        "failed_history": after_failure,
        "failed_history_persisted": failed.failed_history_persisted,
        "sentinel_existed_after_failure": sentinel_exists,
        "sentinel_rows_after_failure": sentinel_rows,
        "prior_write_rolled_back": prior_write_rolled_back,
        "lock_rows_after_failure": lock_rows,
        "retried_migrations": _scripts(retried),
        "final_rows": [[1, "repaired"]],
    }


def _async_silent(work: Path) -> dict:
    migrations = work / "async"
    shutil.copytree(work / "fixtures" / "core", migrations)
    database = work / "async.sqlite"
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(database), "schema": "main"}}
    )

    async def run() -> None:
        async with AsyncDBLiftClient.from_config(
            config, migrations_dir=migrations, logger=NullLog()
        ) as client:
            assert (await client.migrate(placeholders={"seed_value": "fixture-seed"})).success
            assert (await client.info()).success
            assert (await client.validate()).success
            repeatable = migrations / "R__item_view.sql"
            repeatable.write_text(
                repeatable.read_text(encoding="utf-8") + "\n-- repeatable checksum changed\n",
                encoding="utf-8",
            )
            rerun = await client.migrate(placeholders={"seed_value": "fixture-seed"})
            assert rerun.success and [item.script for item in rerun.migrations] == [
                "R__item_view.sql"
            ]
            assert (await client.undo(target_version="0.0.0")).success

    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        asyncio.run(run())
    assert out.getvalue() == err.getvalue() == ""
    history = _history(database)
    sync_async_rows_match = history == _history(work / "core.sqlite")
    assert sync_async_rows_match
    assert _rows(database, "SELECT name FROM sqlite_master WHERE name='items'") == []
    return {
        "sync_async_rows_match": sync_async_rows_match,
        "stdout": out.getvalue(),
        "stderr": err.getvalue(),
    }


def _concurrent_worker(database: Path, migrations: Path, gate: Path, ready: Path) -> None:
    origin = Path(dblift.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert "/site-packages/dblift/" in str(origin)
    with _client(database, migrations) as client:
        ready.touch()
        deadline = time.monotonic() + 20
        while not gate.exists():
            if time.monotonic() > deadline:
                raise TimeoutError("concurrent start gate was not opened")
            time.sleep(0.01)
        result = client.migrate(placeholders={"seed_value": "fixture-seed"})
    print(
        json.dumps(
            {"success": result.success, "applied": len(result.migrations), "origin": str(origin)}
        )
    )


def _concurrent(work: Path) -> dict:
    migrations = work / "concurrent"
    migrations.mkdir()
    for name in ("V1__items.sql", "V2__notes.sql"):
        shutil.copyfile(work / "fixtures" / "core" / name, migrations / name)
    database = work / "concurrent.sqlite"
    gate = work / "concurrent-gate"
    processes = []
    for number in range(2):
        ready = work / f"concurrent-ready-{number}"
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(Path(__file__).resolve()),
                    "--concurrent-worker",
                    str(database),
                    str(migrations),
                    str(gate),
                    str(ready),
                    json.dumps(sorted(REMOVED)),
                ],
                cwd=work,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    try:
        deadline = time.monotonic() + 20
        while not all((work / f"concurrent-ready-{number}").exists() for number in range(2)):
            if time.monotonic() > deadline:
                raise TimeoutError("concurrent workers did not become ready")
            time.sleep(0.01)
        gate.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=90)
            assert process.returncode == 0, stderr
            assert not stderr
            results.append(json.loads(stdout))
        assert all(item["success"] for item in results)
        assert sorted(item["applied"] for item in results) == [0, 2]
        assert all(
            Path(item["origin"]).resolve() == Path(dblift.__file__).resolve() for item in results
        )
        history = _history(database)
        assert len(history) == 2 and all(item[-1] == 1 for item in history)
        assert _rows(database, "SELECT id, value FROM items") == [[1, "fixture-seed"]]
        assert _rows(database, "SELECT id, item_id FROM notes") == [[1, 1]]
        assert _rows(database, f'SELECT * FROM "{MIGRATION_LOCK_TABLE}"') == []
        return {"applied_per_process": [0, 2], "history": history, "worker_origins_verified": True}
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


def _cli_matrix(work: Path) -> dict:
    cli = Path(sysconfig.get_path("scripts")) / ("dblift-fork-fixture" if REMOVED else "dblift")
    assert cli.is_file()
    cli_runner = (
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "--cli",
            json.dumps(sorted(REMOVED)),
            str(cli),
        ]
        if REMOVED
        else [sys.executable, "-I", str(cli)]
    )
    observations = []
    for log_format in ("text", "json", "html", "text,html"):
        root = work / f"cli-{log_format.replace(',', '-')}"
        root.mkdir()
        shutil.copytree(work / "fixtures" / "cli_error", root / "migrations")
        command = [
            *cli_runner,
            "--db-url",
            "sqlite:///db.sqlite",
            "--scripts",
            "migrations",
            "--log-dir",
            "logs",
            "--log-format",
            log_format,
            "migrate",
            "--show-sql",
            "--format",
            "json",
        ]
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=60)
        assert completed.returncode == 1, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["success"] is False
        assert "missing_table" in payload["error"]
        migrations = [[row["script"], row["status"]] for row in payload["migrations"]]
        assert migrations == [["V1__ok.sql", "SUCCESS"], ["V2__bad.sql", "FAILED"]]
        statements = [[row["script"], row["statements"]] for row in payload["sql"]]
        assert statements == [
            ["V1__ok.sql", ["CREATE TABLE cli_items (id INTEGER PRIMARY KEY);"]],
            ["V2__bad.sql", ["INSERT INTO missing_table VALUES (1);"]],
        ]
        reports = sorted((root / "logs").iterdir())
        assert len(reports) == (2 if log_format == "text,html" else 1)
        for report in reports:
            content = report.read_text(encoding="utf-8")
            assert "missing_table" in content
            if report.suffix == ".json":
                assert json.loads(content)["status"] == "FAILED"
            elif report.suffix == ".html":
                assert "temporary file" not in content.lower()
        observations.append(
            {
                "log_format": log_format,
                "exit": completed.returncode,
                "error": payload["error"],
                "migrations": migrations,
                "statements": statements,
                "report_suffixes": [report.suffix for report in reports],
            }
        )
    assert all(
        [row["error"], row["migrations"], row["statements"]]
        == [observations[0]["error"], observations[0]["migrations"], observations[0]["statements"]]
        for row in observations
    )
    text_root = work / "cli-text-stdout"
    text_root.mkdir()
    shutil.copytree(work / "fixtures" / "cli_error", text_root / "migrations")
    text = subprocess.run(
        [
            *cli_runner,
            "--db-url",
            "sqlite:///db.sqlite",
            "--scripts",
            "migrations",
            "--log-dir",
            "logs",
            "--log-format",
            "text",
            "migrate",
            "--show-sql",
            "--format",
            "console",
        ],
        cwd=text_root,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert text.returncode == 1
    assert "FAILED" in text.stdout and "V2__bad.sql" in text.stdout
    assert "missing_table" in text.stderr
    assert "V1__ok.sql" in text.stderr and "V2__bad.sql" in text.stderr
    success_root = work / "cli-success"
    success_root.mkdir()
    success_migrations = success_root / "migrations"
    shutil.copytree(work / "fixtures" / "core", success_migrations)
    common = [
        *cli_runner,
        "--db-url",
        "sqlite:///db.sqlite",
        "--scripts",
        "migrations",
        "--log-dir",
        "logs",
    ]

    def success_command(*args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [*common, *args], cwd=success_root, text=True, capture_output=True, timeout=60
        )
        assert completed.returncode == 0, completed.stderr + completed.stdout
        return completed

    migrated = success_command(
        "migrate", "--placeholders", "seed_value=fixture-seed", "--show-sql", "--format", "json"
    )
    migrated_payload = json.loads(migrated.stdout)
    assert migrated_payload["success"] is True
    assert _rows(success_root / "db.sqlite", "SELECT id, value FROM items") == [[1, "fixture-seed"]]
    unchanged = success_command(
        "migrate", "--placeholders", "seed_value=fixture-seed", "--format", "json"
    )
    assert json.loads(unchanged.stdout)["migrations"] == []
    repeatable = success_migrations / "R__item_view.sql"
    repeatable.write_text(
        repeatable.read_text(encoding="utf-8") + "\n-- repeatable checksum changed\n",
        encoding="utf-8",
    )
    rerun = success_command(
        "migrate", "--placeholders", "seed_value=fixture-seed", "--format", "json"
    )
    rerun_migrations = [row["script"] for row in json.loads(rerun.stdout)["migrations"]]
    assert rerun_migrations == ["R__item_view.sql"]
    undone = success_command("undo", "--target-version", "0.0.0", "--show-sql")
    assert (
        _rows(
            success_root / "db.sqlite",
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('items', 'notes')",
        )
        == []
    )
    cli_final_history = _history(success_root / "db.sqlite")
    assert cli_final_history == _history(work / "core.sqlite")
    return {
        "formats": observations,
        "text_stdout_contains_error": True,
        "text_stderr_contains_sql": True,
        "text_exit": text.returncode,
        "success_cli": {
            "migrate_success": migrated_payload["success"],
            "migrate_sql": [row["statements"] for row in migrated_payload["sql"]],
            "repeatable_applied": rerun_migrations == ["R__item_view.sql"],
            "undo_success": undone.returncode == 0,
            "history_after_undo": cli_final_history,
        },
    }


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        cli = Path(sys.argv[3])
        sys.argv = [str(cli), *sys.argv[4:]]
        runpy.run_path(str(cli), run_name="__main__")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--concurrent-worker":
        _concurrent_worker(*(Path(value) for value in sys.argv[2:6]))
        return
    origin = Path(dblift.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert "/site-packages/dblift/" in str(origin)
    assert Path.cwd() != Path(__file__).resolve().parents[2]
    if REMOVED:
        try:
            importlib.util.find_spec(f"dblift.db.plugins.{next(iter(REMOVED))}")
        except ModuleNotFoundError as exc:
            assert "Removed provider imported" in str(exc)
        else:
            raise AssertionError("removed provider import blocker was inactive")
    cases = []
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
        for requirement, command, runner in (
            ("L5-02", "API migrate/info/validate/repeatable/undo", _core),
            ("L2-02", "silent sync and async API", _async_silent),
            ("L5-04", "API failed SQL/repair/retry", _invalid),
            ("L5-05", "two concurrent installed-wheel processes", _concurrent),
            ("L2-04", "CLI JSON/error under text, JSON, HTML and combined logs", _cli_matrix),
        ):
            try:
                evidence = runner(Path.cwd())
                cases.append(
                    {
                        "requirement": requirement,
                        "dialect": "sqlite",
                        "command": command,
                        "outcome": "pass",
                        "evidence": evidence,
                        "limitation": "",
                    }
                )
                if requirement == "L5-02":
                    cases.append(
                        {
                            "requirement": "L5-03",
                            "dialect": "sqlite",
                            "command": "API validate changed/restored checksum",
                            "outcome": "pass",
                            "evidence": {"drift_issue_count": evidence["drift_issue_count"]},
                            "limitation": "",
                        }
                    )
            except Exception as exc:
                cases.append(
                    {
                        "requirement": requirement,
                        "dialect": "sqlite",
                        "command": command,
                        "outcome": "fail",
                        "evidence": f"{type(exc).__name__}: {exc}",
                        "limitation": "",
                    }
                )
    if captured_out.getvalue() or captured_err.getvalue():
        cases.append(
            {
                "requirement": "L2-02",
                "dialect": "sqlite",
                "command": "silent API channels",
                "outcome": "fail",
                "evidence": {
                    "stdout": captured_out.getvalue()[:500],
                    "stderr": captured_err.getvalue()[:500],
                },
                "limitation": "",
            }
        )
    print(
        json.dumps(
            {
                "status": "pass" if all(case["outcome"] == "pass" for case in cases) else "fail",
                "origin": str(origin),
                "workdir": str(Path.cwd().resolve()),
                "history_table": DEFAULT_HISTORY_TABLE,
                "removed_imports_blocked": bool(REMOVED),
                "cases": cases,
            }
        )
    )


if __name__ == "__main__":
    main()
