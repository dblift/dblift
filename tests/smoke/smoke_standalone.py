"""Verify archive identity, then exercise the extracted CLI from a separate project."""

import argparse
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from build_standalone import TARGETS, read_release_wheel, sha256  # noqa: E402


def read_archive(archive_dir, target):
    extension = TARGETS[target][2]
    archives = sorted(archive_dir.glob(f"dblift-*-{target}{extension}"))
    if len(archives) != 1:
        raise ValueError(f"Expected one {target} archive in {archive_dir}")
    archive = archives[0]
    checksum = (archive_dir / f"{archive.name}.sha256").read_text(encoding="utf-8").split()
    if checksum != [sha256(archive), archive.name]:
        raise ValueError(f"Archive SHA-256 mismatch: {archive.name}")
    print(f"{checksum[0]}  {archive.name} [verified]", flush=True)
    return archive


def extract_archive(archive, bundle):
    if archive.suffix == ".zip":
        with ZipFile(archive) as zip_file:
            zip_file.extractall(bundle)
    else:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(bundle, filter="data")


def verify_bundle(bundle, archive, target, wheel_dir):
    identity = json.loads((bundle / "build-identity.json").read_text(encoding="utf-8"))
    version = identity["version"]
    wheel_name = f"dblift-{version}-py3-none-any.whl"
    if (
        identity["target"] != target
        or identity["wheel"] != wheel_name
        or archive.name != f"dblift-{version}-{target}{TARGETS[target][2]}"
        or not re.fullmatch(r"[a-f0-9]{64}", identity["wheel_sha256"])
    ):
        raise ValueError(f"Build identity differs from archive: {archive.name}")
    if wheel_dir is not None:
        wheel, _, license_text = read_release_wheel(wheel_dir)
        if wheel.name != wheel_name or identity["wheel_sha256"] != sha256(wheel):
            raise ValueError(f"Packaged wheel identity differs from input: {wheel.name}")
        if (bundle / "LICENSE").read_bytes() != license_text:
            raise ValueError(f"Packaged license differs from input: {wheel.name}")

    notices = bundle / "licenses"
    if (
        not (bundle / "LICENSE").stat().st_size
        or not (notices / "Python-LICENSE.txt").stat().st_size
    ):
        raise ValueError("Missing runtime notices")
    hashes = (notices / "native-library-sha256.txt").read_text(encoding="utf-8").splitlines()
    if not hashes:
        raise ValueError("Missing native library hashes")
    for line in hashes:
        digest, path = line.split("  ", 1)
        resolved = (bundle / path).resolve()
        if not resolved.is_relative_to(bundle) or sha256(resolved) != digest:
            raise ValueError(f"Native library SHA-256 mismatch: {path}")

    print(f"Wheel {wheel_name} SHA-256 {identity['wheel_sha256']}", flush=True)
    print(f"Verified all {len(hashes)} native library hashes", flush=True)
    return version


def capture_cli(cli, project, env, *arguments):
    result = subprocess.run(
        [cli, *arguments],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    output = result.stdout + result.stderr
    if output:
        print(output, end="", flush=True)
    return result


def run_cli(cli, project, env, *arguments):
    result = capture_cli(cli, project, env, *arguments)
    result.check_returncode()
    return result.stdout + result.stderr


def probe_postgres_driver(cli, project, env):
    # macOS drops connections to a bound socket until it is released or listens.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    probe_env = dict(
        {key: value for key, value in env.items() if not key.upper().startswith("PG")},
        LC_ALL="C",
        PSYCOPG_IMPL="binary",
        PGCONNECT_TIMEOUT="3",
        DBLIFT_DB_URL=(
            f"postgresql+psycopg://standalone:standalone@127.0.0.1:{port}"
            "/standalone?hostaddr=127.0.0.1&connect_timeout=3"
        ),
    )
    result = capture_cli(cli, project, probe_env, "--log-level", "debug", "db", "check-connection")
    if result.returncode <= 0 or not re.search(
        r"^psycopg\.OperationalError: .*"
        r"(?:\b(?:connection|actively)\s+refused\b|0x0000274d/10061\b|\[WinError 10061\])",
        result.stderr,
        re.IGNORECASE | re.MULTILINE,
    ):
        raise ValueError("PostgreSQL driver did not report a refused loopback connection")
    print("PostgreSQL binary driver loaded and reached the refused loopback connection", flush=True)


def sqlite_table_exists(database, table_name):
    if not database.exists():
        return False
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?", (table_name,)
        ).fetchone()
    return row is not None


def exercise_cli(workspace, cli, version):
    project = workspace / "project"
    home = workspace / "home"
    migrations = project / "migrations"
    migrations.mkdir(parents=True)
    home.mkdir()
    migration = migrations / "V1__create_example.sql"
    migration.write_text(
        "CREATE TABLE standalone_example (id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    (migrations / "U1__drop_example.sql").write_text(
        "DROP TABLE standalone_example;\n", encoding="utf-8"
    )
    database_url = os.environ.get("DBLIFT_STANDALONE_SMOKE_DB_URL", "sqlite:///smoke.db")
    dialect = os.environ.get("DBLIFT_STANDALONE_SMOKE_DIALECT", "sqlite")
    sqlite_database = project / "smoke.db" if database_url == "sqlite:///smoke.db" else None
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DBLIFT_") and key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env.update(HOME=str(home), USERPROFILE=str(home), DBLIFT_DB_URL=database_url)

    version_output = run_cli(cli, project, env, "--version").strip()
    if version_output != f"dblift version {version}":
        raise ValueError(f"Unexpected executable version: {version_output}")
    run_cli(cli, project, env, "db", "check-connection")
    run_cli(cli, project, env, "validate-sql", "--files", str(migration), "--dialect", dialect)
    preview = run_cli(cli, project, env, "migrate", "--dry-run", "--show-sql")
    if "CREATE TABLE standalone_example" not in preview:
        raise ValueError("Dry run did not print the migration SQL")
    if sqlite_database is not None and sqlite_table_exists(sqlite_database, "standalone_example"):
        raise ValueError("Dry run changed the SQLite database")
    run_cli(cli, project, env, "migrate")
    if sqlite_database is not None and not sqlite_table_exists(
        sqlite_database, "standalone_example"
    ):
        raise ValueError("Migration did not create the expected SQLite table")
    run_cli(cli, project, env, "info")
    run_cli(cli, project, env, "validate")
    undo = run_cli(cli, project, env, "undo")
    if "Successfully undone migration V1__create_example.sql" not in undo:
        raise ValueError("Undo did not reverse the applied migration")
    if sqlite_database is not None and (
        sqlite_table_exists(sqlite_database, "standalone_example")
        or not sqlite_table_exists(sqlite_database, "dblift_schema_history")
    ):
        raise ValueError("Undo did not leave the expected SQLite schema and history")
    if sqlite_database is not None:
        probe_postgres_driver(cli, project, env)


def smoke(archive_dir, target, wheel_dir):
    archive = read_archive(archive_dir, target)
    with tempfile.TemporaryDirectory(prefix="dblift-smoke-") as folder:
        workspace = Path(folder).resolve()
        bundle = workspace / "archive"
        bundle.mkdir()
        extract_archive(archive, bundle)
        version = verify_bundle(bundle, archive, target, wheel_dir)
        cli = bundle / ("dblift.exe" if target == "windows-x86_64" else "dblift")
        exercise_cli(workspace, cli, version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--wheel-dir", type=Path)
    args = parser.parse_args()
    try:
        smoke(args.archive_dir, args.target, args.wheel_dir)
    except (
        BadZipFile,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
