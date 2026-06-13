"""Integration test: CosmosDB snapshot persistence after migrate.

Requires: CosmosDB emulator running at http://localhost:8081/
"""

import json
import os
import subprocess
import sys

import pytest

DBLIFT = [sys.executable, "-m", "cli.main"]
EMULATOR_KEY = (
    # Standard Azure CosmosDB emulator default key — not a real secret
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)


@pytest.fixture(scope="module")
def cosmosdb_config(tmp_path_factory):
    config_path = tmp_path_factory.mktemp("cfg") / "cosmosdb_snap.yaml"
    config_path.write_text(
        "database:\n"
        "  type: cosmosdb\n"
        "  account_endpoint: http://localhost:8081/\n"
        f"  account_key: {EMULATOR_KEY}\n"
        "  database_name: snap_integ_test\n"
    )
    return str(config_path)


@pytest.fixture(scope="module")
def migrations_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("mig")
    (d / "V1__create_items.sql").write_text(
        "CREATE CONTAINER snap_items (id STRING) WITH (partitionKey='/id')"
    )
    return str(d)


@pytest.mark.integration
@pytest.mark.cosmosdb
class TestCosmosDbSnapshotPersistence:
    def test_migrate_captures_snapshot(self, cosmosdb_config, migrations_dir, tmp_path):
        """After migrate, snapshot --source database-stored must return a result."""
        # Run migrate
        result = subprocess.run(
            DBLIFT + ["migrate", "--config", cosmosdb_config, "--scripts", migrations_dir],
            capture_output=True,
            text=True,
        )
        assert (
            result.returncode == 0
        ), f"migrate failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"

        # Run snapshot --source database-stored
        snap_file = str(tmp_path / "snap.json")
        result = subprocess.run(
            DBLIFT
            + [
                "snapshot",
                "--config",
                cosmosdb_config,
                "--source",
                "database-stored",
                "--output",
                snap_file,
            ],
            capture_output=True,
            text=True,
        )
        assert (
            result.returncode == 0
        ), f"snapshot failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        assert os.path.exists(snap_file), "snapshot output file not written"

        with open(snap_file) as f:
            data = json.load(f)
        # Snapshot must have some content — CosmosDB uses containers not tables
        assert isinstance(data, dict), f"unexpected snapshot type: {type(data)}"
        assert len(data) > 0, f"snapshot is empty dict"
