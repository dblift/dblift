"""Serve the interface with three seeded SQLite projects, for the browser tests only."""

import contextlib
import sys
import tempfile
from pathlib import Path

import uvicorn
from dblift_ui.registry import ProjectRegistry
from dblift_ui.server import create_app

TOKEN = "e2e-token"


def seed(root: Path, name: str, scripts: dict[str, str]) -> Path:
    project = root / name
    (project / "migrations").mkdir(parents=True)
    for file_name, sql in scripts.items():
        (project / "migrations" / file_name).write_text(sql)
    config = project / "dblift.yaml"
    config.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"
    )
    return config


def main() -> None:
    port = int(sys.argv[1])
    with tempfile.TemporaryDirectory(prefix="dblift-ui-e2e-") as tmp:
        root = Path(tmp)
        registry = ProjectRegistry(root / "state" / "projects.json")
        registry.add(
            "shop",
            str(
                seed(
                    root,
                    "shop",
                    {
                        "V1_0_0__create_customers.sql": "CREATE TABLE customers (id INTEGER PRIMARY KEY);\n",
                        "U1_0_0__create_customers.sql": "DROP TABLE customers;\n",
                        "V1_0_1__create_orders.sql": "CREATE TABLE orders (id INTEGER PRIMARY KEY);\n",
                        "U1_0_1__create_orders.sql": "DROP TABLE orders;\n",
                    },
                )
            ),
        )
        registry.add(
            "broken",
            str(
                seed(
                    root,
                    "broken",
                    {
                        "V1_0_0__create_events.sql": "CREATE TABLE events (id INTEGER PRIMARY KEY);\n",
                        "V1_0_1__typo.sql": "SELEC nonsense;\n",
                    },
                )
            ),
        )
        registry.add(
            "notes",
            str(
                seed(
                    root,
                    "notes",
                    {
                        "V1_0_0__create_notes.sql": "CREATE TABLE notes (id INTEGER PRIMARY KEY);\n",
                        "U1_0_0__create_notes.sql": "DROP TABLE notes;\n",
                    },
                )
            ),
        )
        # Playwright stops the server with SIGINT; uvicorn shuts down, then re-raises it
        # as KeyboardInterrupt, and leaving this block removes the seeded projects.
        with contextlib.suppress(KeyboardInterrupt):
            uvicorn.run(
                create_app(token=TOKEN, port=port, registry=registry),
                host="127.0.0.1",
                port=port,
                log_level="warning",
            )


if __name__ == "__main__":
    main()
