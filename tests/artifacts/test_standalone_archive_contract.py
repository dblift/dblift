"""The standalone build consumes one release wheel, and smoke verifies its archive."""

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
        with pytest.raises(ValueError, match="PostgreSQL driver did not report a refused"):
            smoke_standalone.probe_postgres_driver(tmp_path / "dblift", tmp_path, env)
