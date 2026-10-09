"""Info shows undo companions from every configured scripts directory."""

import os
import re
import subprocess
import sys

import pytest
import yaml

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("source", ["cli", "yaml"])
@pytest.mark.parametrize("applied", [False, True])
def test_info_undoable_uses_all_script_directories(tmp_path, monkeypatch, source, reverse, applied):
    migrations = tmp_path / "migrations"
    rollback = tmp_path / "rollback"
    migrations.mkdir()
    rollback.mkdir()
    (migrations / "V2__add_price.sql").write_text("CREATE TABLE prices (price INTEGER);")
    (rollback / "U2__drop_price.sql").write_text("DROP TABLE prices;")
    directories = [migrations, rollback]
    if reverse:
        directories.reverse()
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite")},
                "migrations": {"directories": [str(path) for path in directories]},
            }
        )
    )
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)
    script_flags = (
        [value for path in directories for value in ("--scripts", str(path))]
        if source == "cli"
        else []
    )
    command = [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *script_flags]
    if applied:
        migrated = subprocess.run([*command, "migrate"], capture_output=True, text=True, timeout=30)
        assert migrated.returncode == 0, migrated.stdout + migrated.stderr
    result = subprocess.run(
        [*command, "info"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    row = next(line for line in result.stdout.splitlines() if "add_price" in line)
    assert ("Success" if applied else "Pending") in row, row
    assert re.search(r"\bYes\b", row), row
