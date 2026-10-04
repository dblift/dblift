"""Exercise the installed SQLite fork without loading any removed provider."""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import os
import runpy
import sqlite3
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path


class RemovedProviderBlocker(importlib.abc.MetaPathFinder):
    def __init__(self, removed: set[str]) -> None:
        self.removed = removed

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        if (
            len(parts) >= 4
            and parts[:3] == ["dblift", "db", "plugins"]
            and parts[3] in self.removed
        ):
            raise ModuleNotFoundError(f"Removed provider imported: {fullname}")
        return None


def run(args: list[str], work: Path) -> str:
    result = subprocess.run(args, cwd=work, capture_output=True, text=True, check=True, timeout=120)
    return result.stdout


def main() -> None:
    if sys.argv[1] == "--cli":
        removed = set(json.loads(sys.argv[2]))
        cli = Path(sys.argv[3])
        sys.meta_path.insert(0, RemovedProviderBlocker(removed))
        sys.argv = [str(cli), *sys.argv[4:]]
        runpy.run_path(str(cli), run_name="__main__")
        return
    removed = set(json.loads(sys.argv[2]))
    sys.meta_path.insert(0, RemovedProviderBlocker(removed))
    import dblift
    from dblift.config import DbliftConfig
    from dblift.core.constants import (
        DBLIFT_DATA_AUDIT_TABLE,
        DBLIFT_DATA_CHANGE_SET_TABLE,
        DBLIFT_SCHEMA_SNAPSHOTS_TABLE,
        DEFAULT_HISTORY_TABLE,
        ENV_PREFIX,
        MIGRATION_LOCK_TABLE,
    )
    from dblift.db.provider_registry import ProviderRegistry

    work = Path(sys.argv[1])
    origin = Path(dblift.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert "/site-packages/dblift/" in str(origin)
    distribution = metadata.distribution("dblift-sqlite-fork-fixture")
    own = sorted(
        {
            d.metadata["Name"].lower()
            for d in metadata.distributions()
            if d.metadata["Name"].lower().startswith("dblift")
        }
    )
    assert own == ["dblift-sqlite-fork-fixture"]
    assert importlib.util.find_spec("dblift_pro") is None
    assert importlib.util.find_spec("dblift_enterprise") is None
    assert importlib.util.find_spec("dblift.core.premium_manifest") is not None
    providers = sorted(ep.name for ep in metadata.entry_points(group="dblift.providers"))
    assert providers == ["sqlite"]
    assert [p.name for p in ProviderRegistry.list_plugins()] == ["sqlite"]
    assert ENV_PREFIX == "FORKLIFT_"
    assert DEFAULT_HISTORY_TABLE == "forklift_schema_history"
    assert MIGRATION_LOCK_TABLE == "forklift_migration_lock"
    assert DBLIFT_SCHEMA_SNAPSHOTS_TABLE == "forklift_schema_snapshots"
    assert DBLIFT_DATA_CHANGE_SET_TABLE == "forklift_data_change_set"
    assert DBLIFT_DATA_AUDIT_TABLE == "forklift_data_audit"
    os.environ.pop("FORKLIFT_DB_URL", None)
    os.environ["DBLIFT_DB_URL"] = "sqlite:///wrong.sqlite"
    original_env_ignored = "database" not in DbliftConfig.from_env_dict()
    os.environ["FORKLIFT_DB_URL"] = "sqlite:///fork.sqlite"
    resolved = DbliftConfig.from_dict(DbliftConfig.from_env_dict())
    fork_env_selected = resolved.database.url == "sqlite:///fork.sqlite"
    assert original_env_ignored and fork_env_selected
    os.environ.pop("DBLIFT_DB_URL", None)
    os.environ.pop("FORKLIFT_DB_URL", None)

    cli = Path(sysconfig.get_path("scripts")) / "dblift-fork-fixture"
    assert cli.is_file()
    runner = [
        sys.executable,
        "-I",
        str(Path(__file__)),
        "--cli",
        json.dumps(sorted(removed)),
        str(cli),
    ]
    help_text = run([*runner, "--help"], work)
    assert "migrate" in help_text and "validate" in help_text
    for premium in ("diff", "export-schema", "snapshot", "validate-sql", "plan", "preflight"):
        assert premium in help_text
    assert distribution.version in run([*runner, "--version"], work)
    migrations = work / "migrations"
    migrations.mkdir()
    (migrations / "V1__fork.sql").write_text(
        "CREATE TABLE fork_probe (id INTEGER PRIMARY KEY, value TEXT);\n"
        "INSERT INTO fork_probe (id, value) VALUES (1, 'forked');\n",
        encoding="utf-8",
    )
    database = work / "fork.sqlite"
    config = work / "fork.yaml"
    config.write_text(f"database:\n  type: sqlite\n  path: {database}\n", encoding="utf-8")
    migrate = run(
        [*runner, "migrate", "--config", str(config), "--scripts", str(migrations)],
        work,
    )
    run(
        [*runner, "validate", "--config", str(config), "--scripts", str(migrations)],
        work,
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM fork_probe WHERE id=1").fetchone() == (
            "forked",
        )
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert DEFAULT_HISTORY_TABLE in tables
    assert MIGRATION_LOCK_TABLE in tables
    print(
        json.dumps(
            {
                "origin": str(origin),
                "distributions": own,
                "providers": providers,
                "sqlite_migrate": bool(migrate),
                "history_table": DEFAULT_HISTORY_TABLE,
                "lock_table": MIGRATION_LOCK_TABLE,
                "fork_env_selected": fork_env_selected,
                "original_env_ignored": original_env_ignored,
            }
        )
    )


if __name__ == "__main__":
    main()
