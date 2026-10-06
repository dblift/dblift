"""``dblift migrate`` runs its registered pre-migrate checks before opening the database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import dblift.cli.main as cli_main
from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.core.seams import runtime_checks
from dblift.core.seams.capabilities import CapabilityDeniedError

pytestmark = [pytest.mark.unit]

UNREACHABLE_URL = "postgresql://u:p@127.0.0.1:1/db"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);\n")
    monkeypatch.chdir(tmp_path)
    for key in [k for k in os.environ if k.startswith("DBLIFT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_checks():
    runtime_checks.clear_checks()
    yield
    runtime_checks.clear_checks()


def _migrate(monkeypatch: pytest.MonkeyPatch, url: str) -> int:
    monkeypatch.setattr(
        "sys.argv", ["dblift", "--db-url", url, "--scripts", "migrations", "migrate"]
    )
    try:
        cli_main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_refusing_pre_migrate_check_runs_before_the_database_is_opened(project, monkeypatch):
    def refuse() -> None:
        raise CapabilityDeniedError("migrate needs a licence")

    runtime_checks.register_check("command.pre_migrate", refuse)
    assert _migrate(monkeypatch, "sqlite:///x.db") == EXIT_LICENSE_REQUIRED
    assert not (project / "x.db").exists()


def test_migrate_without_checks_still_connects_and_applies(project, monkeypatch):
    assert _migrate(monkeypatch, "sqlite:///x.db") == 0
    assert (project / "x.db").exists()


def test_unreachable_database_is_reported_as_a_connection_error(project, monkeypatch, capsys):
    assert _migrate(monkeypatch, UNREACHABLE_URL) == 1
    out = capsys.readouterr()
    assert "ConnectionError: Connection failed: host unreachable" in out.out + out.err
