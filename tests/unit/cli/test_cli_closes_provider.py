"""The CLI closes the database provider on every exit path."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

import dblift.cli.main as cli_main
from dblift.db.plugins.sqlite.provider import SQLiteProvider

pytestmark = [pytest.mark.unit]


def _project(tmp_path: Path, sql: str) -> Path:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "V1__init.sql").write_text(sql, encoding="utf-8")
    return tmp_path


def _run_main(project: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.chdir(project)
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")
    for key in [
        k for k in os.environ if k.startswith("DBLIFT_") and k != "DBLIFT_DISABLE_CLI_EXTENSIONS"
    ]:
        monkeypatch.delenv(key)
    monkeypatch.setattr(
        "sys.argv",
        ["dblift", "--db-url", "sqlite:///app.db", "--scripts", "migrations", "migrate"],
    )
    try:
        cli_main.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _count_closes(project: Path, monkeypatch: pytest.MonkeyPatch) -> "tuple[int, int]":
    real_close = SQLiteProvider.close
    calls: list[int] = []

    def counting_close(self: SQLiteProvider) -> None:
        calls.append(1)
        real_close(self)

    with patch.object(SQLiteProvider, "close", counting_close):
        code = _run_main(project, monkeypatch)
    return code, len(calls)


def test_provider_closed_after_successful_command(tmp_path, monkeypatch):
    project = _project(tmp_path, "CREATE TABLE t (id INTEGER);\n")

    code, closes = _count_closes(project, monkeypatch)

    assert code == 0
    assert closes == 1


def test_provider_closed_after_failed_command(tmp_path, monkeypatch):
    project = _project(tmp_path, "THIS IS NOT SQL;\n")

    code, closes = _count_closes(project, monkeypatch)

    assert code == 1
    assert closes == 1


def test_close_failure_does_not_mask_exit_code(tmp_path, monkeypatch):
    project = _project(tmp_path, "THIS IS NOT SQL;\n")

    with patch.object(SQLiteProvider, "close", side_effect=RuntimeError("boom")):
        code = _run_main(project, monkeypatch)

    assert code == 1
