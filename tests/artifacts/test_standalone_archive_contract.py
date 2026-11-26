"""The standalone build consumes one release wheel, and smoke verifies its archive."""

import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.smoke import smoke_standalone

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("wheel_count", [0, 2])
def test_build_rejects_missing_or_ambiguous_wheel(tmp_path, wheel_count):
    for i in range(wheel_count):
        (tmp_path / f"dblift-{i}.0.0-py3-none-any.whl").touch()
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/build_standalone.py"),
            "--wheel-dir",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--target",
            "linux-x86_64",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Expected exactly one DBLift release wheel" in result.stderr
    assert not (tmp_path / "out").exists()


def test_smoke_rejects_archive_with_wrong_digest(tmp_path):
    name = "dblift-5.2.0-linux-x86_64.tar.gz"
    (tmp_path / name).write_bytes(b"not the released archive")
    (tmp_path / f"{name}.sha256").write_text(f"{'0' * 64}  {name}\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tests/smoke/smoke_standalone.py"),
            "--archive-dir",
            str(tmp_path),
            "--target",
            "linux-x86_64",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Archive SHA-256 mismatch" in result.stderr


@pytest.mark.parametrize(
    ("returncode", "diagnostic", "expected"),
    [
        (1, "psycopg.OperationalError: connection failed: Connection refused", True),
        (
            1,
            "psycopg.OperationalError: No connection could be made because the target machine "
            "actively refused it.",
            True,
        ),
        (1, "psycopg.OperationalError: unrecognized socket error: 0x0000274D/10061", True),
        (1, "psycopg.OperationalError: [WinError 10061]", True),
        (1, "psycopg.OperationalError: port 10061 failed: Operation timed out", False),
        (1, "ImportError: no pq wrapper available", False),
        (1, "Connection failed: host unreachable", False),
        (1, "Connection refused", False),
        (0, "psycopg.OperationalError: connection failed: Connection refused", False),
    ],
)
def test_native_postgres_probe_requires_driver_refusal(
    monkeypatch, tmp_path, returncode, diagnostic, expected
):
    def capture(cli, project, env, *args):
        assert env["PSYCOPG_IMPL"] == "binary"
        url = urlsplit(env["DBLIFT_DB_URL"])
        assert url.scheme == "postgresql+psycopg"
        assert url.hostname == "127.0.0.1"
        assert parse_qs(url.query)["hostaddr"] == ["127.0.0.1"]
        assert parse_qs(url.query)["connect_timeout"] == ["3"]
        assert "PGHOSTADDR" not in env
        assert "pgservice" not in env
        assert args == ("--log-level", "debug", "db", "check-connection")
        return subprocess.CompletedProcess(args, returncode, "", diagnostic)

    monkeypatch.setattr(smoke_standalone, "capture_cli", capture)
    env = {"PGHOSTADDR": "198.51.100.1", "pgservice": "external"}
    if expected:
        smoke_standalone.probe_postgres_driver(tmp_path / "dblift", tmp_path, env)
    else:
        with pytest.raises(ValueError, match="PostgreSQL driver did not report the expected"):
            smoke_standalone.probe_postgres_driver(tmp_path / "dblift", tmp_path, env)


def test_smoke_relays_frozen_utf8_output_when_parent_has_legacy_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    smoke_path = ROOT / "tests" / "smoke" / "smoke_standalone.py"
    driver = """
import os
import runpy
import sys
from pathlib import Path

main = runpy.run_path(sys.argv[1])["main"]
capture_cli = main.__globals__["capture_cli"]

def check_archive(*args):
    result = capture_cli(
        sys.executable, Path.cwd(), os.environ.copy(), "-I", "-X", "utf8",
        "-c", "print(chr(0x2705))"
    )
    result.check_returncode()

main.__globals__["smoke"] = check_archive
sys.argv = [sys.argv[1], "--archive-dir", ".", "--target", "windows-x86_64"]
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", driver, str(smoke_path)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.decode("utf-8").strip() == "✅"


@pytest.mark.parametrize(("host_platform", "accepted"), [("win32", True), ("darwin", False)])
def test_driver_probe_handles_observed_windows_timeout(
    tmp_path, monkeypatch, host_platform, accepted
):
    monkeypatch.setattr(smoke_standalone.sys, "platform", host_platform)
    monkeypatch.setattr(
        smoke_standalone,
        "capture_cli",
        lambda *args: subprocess.CompletedProcess(
            args, 1, "", "psycopg.errors.ConnectionTimeout: connection timeout expired\n"
        ),
    )
    if accepted:
        smoke_standalone.probe_postgres_driver(tmp_path / "dblift", tmp_path, {})
    else:
        with pytest.raises(ValueError, match="PostgreSQL driver did not"):
            smoke_standalone.probe_postgres_driver(tmp_path / "dblift", tmp_path, {})


def test_sqlite_schema_check_closes_database_handle(tmp_path, monkeypatch):
    database = tmp_path / "smoke.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE standalone_probe (id INTEGER PRIMARY KEY)")
        monkeypatch.setattr(smoke_standalone.sqlite3, "connect", lambda path: connection)
        assert smoke_standalone.sqlite_table_exists(database, "standalone_probe")
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


@pytest.mark.parametrize("target", smoke_standalone.TARGETS)
def test_sql_driver_wheels_are_locked_on_each_standalone_target(target):
    lock = ROOT / "scripts" / f"standalone-{target}.requirements.txt"
    names = {
        line.split("==", 1)[0].split("[", 1)[0].lower()
        for line in lock.read_text(encoding="utf-8").splitlines()
        if " --hash=sha256:" in line
    }
    missing = {"oracledb", "pymysql", "pymssql", "cryptography"} - names
    assert not missing, f"{target} lacks locked SQL driver wheels: {sorted(missing)}"


def test_sqlite_archive_smoke_checks_the_bundled_sql_drivers(monkeypatch, tmp_path):
    expected = {
        "postgresql+psycopg",
        "mysql+pymysql",
        "oracle+oracledb",
        "mssql+pymssql",
    }
    diagnostics = {
        "postgresql+psycopg": "psycopg.OperationalError: connection failed: Connection refused",
        "mysql+pymysql": "pymysql.err.OperationalError: (2003, 'Connection refused')",
        "oracle+oracledb": "oracledb.exceptions.OperationalError: DPY-6005: cannot connect",
        "mssql+pymssql": "pymssql.exceptions.OperationalError: (20009, b'DB-Lib message')",
    }
    probed = set()
    tables = {"dblift_schema_history"}

    def capture(cli, project, env, *arguments):
        url = urlsplit(env["DBLIFT_DB_URL"])
        assert url.hostname == "127.0.0.1"
        assert url.port is not None
        assert arguments == ("--log-level", "debug", "db", "check-connection")
        probed.add(url.scheme)
        output = diagnostics[url.scheme]
        if sys.platform == "darwin" and url.scheme == "mssql+pymssql":
            assert env["DYLD_PRINT_LIBRARIES"] == "1"
            for name in ("libssl.3.dylib", "libcrypto.3.dylib"):
                vendor_lib = cli.resolve().parent / "_internal/pymssql/.dylibs" / name
                output += f"\ndyld[123]: <uuid> {vendor_lib}"
        return subprocess.CompletedProcess(arguments, 1, "", output)

    def run(cli, project, env, *arguments):
        if arguments == ("--version",):
            return "dblift version 5.2.0"
        if arguments == ("migrate", "--dry-run", "--show-sql"):
            return "CREATE TABLE standalone_example"
        if arguments == ("migrate",):
            tables.add("standalone_example")
        if arguments == ("undo",):
            tables.remove("standalone_example")
            return "Successfully undone migration V1__create_example.sql"
        return ""

    monkeypatch.delenv("DBLIFT_STANDALONE_SMOKE_DB_URL", raising=False)
    monkeypatch.delenv("DBLIFT_STANDALONE_SMOKE_DIALECT", raising=False)
    monkeypatch.setattr(smoke_standalone, "capture_cli", capture)
    monkeypatch.setattr(smoke_standalone, "run_cli", run)
    monkeypatch.setattr(smoke_standalone, "sqlite_table_exists", lambda _, name: name in tables)

    smoke_standalone.exercise_cli(tmp_path, tmp_path / "dblift", "5.2.0")
    assert probed == expected
