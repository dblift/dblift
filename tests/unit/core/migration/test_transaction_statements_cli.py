"""SQLite and DuckDB: transaction statements in a migration, through ``dblift migrate`` as a subprocess (no container: file databases).

The CLI connects in autocommit, unlike ``from_sqlalchemy``; the same scenarios are held to the same
state on both paths. For a script that is applied, the vendor shell run on the same script is the
oracle. No container: file databases and the engines' own shells.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.transaction_scenarios import SCENARIOS, SCRIPT, cases, database_url, read_state

REPO = Path(__file__).resolve().parents[2]
SHELLS = {"sqlite": ["sqlite3", "-bail"], "duckdb": ["duckdb", "-init", "/dev/null", "-bail"]}


def _migrate(engine_name, directory, script):
    migrations = directory / "m"
    migrations.mkdir()
    (migrations / SCRIPT).write_text(script)
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


@pytest.mark.parametrize("engine_name, name", cases())
def test_scenario(engine_name, name, tmp_path):
    scenario = SCENARIOS[name]
    proc = _migrate(engine_name, tmp_path, scenario.script)
    output = proc.stdout + proc.stderr

    assert (proc.returncode == 0) is (scenario.status == "applied"), output
    assert read_state(engine_name, tmp_path) == (
        scenario.tables,
        scenario.expected_history(),
    ), output
    if scenario.message:
        assert scenario.message in output
    if scenario.status == "refused":
        assert SCRIPT in output
        assert "Failed to parse SQL" not in output


@pytest.mark.parametrize("engine_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("name", ["envelope", "envelope_failing_body"])
def test_envelope_outcome_equals_the_vendor_shell(engine_name, name, tmp_path):
    shell = SHELLS[engine_name]
    if shutil.which(shell[0]) is None:
        pytest.skip(f"{shell[0]} not installed")
    script = SCENARIOS[name].script
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    db = database_url(engine_name, vendor_dir).split("///", 1)[1]
    subprocess.run(shell + [db], input=script, capture_output=True, text=True, timeout=60)
    vendor_tables, _ = read_state(engine_name, vendor_dir)

    dblift_dir = tmp_path / "dblift"
    dblift_dir.mkdir()
    _migrate(engine_name, dblift_dir, script)
    dblift_tables, _ = read_state(engine_name, dblift_dir)

    assert dblift_tables == vendor_tables
