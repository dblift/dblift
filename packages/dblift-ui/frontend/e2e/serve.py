"""Serve the interface with three seeded SQLite projects, for the browser tests only.

A second argument names a folder where fixture repositories are built for the tests
that add projects.
"""

import contextlib
import shutil
import sqlite3
import subprocess
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


def build_fixtures(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
    repo = folder / "monorepo"
    config = "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"
    files = {
        "dblift.yaml": config,
        "migrations/V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
        "services/billing/dblift.yaml": config,
        "services/billing/migrations/V1_0_0__create_invoices.sql": "CREATE TABLE invoices (id INTEGER PRIMARY KEY);\n",
        "dblift.yaml.template": config,
        "legacy/flyway.conf": "flyway.url=jdbc:sqlite:legacy.db\n",
        "legacy/sql/V1__old.sql": "CREATE TABLE old (id INTEGER PRIMARY KEY);\n",
        ".gitignore": "*.db\n",
    }
    for relative, text in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git = ["git", "-c", "user.email=e2e@example.com", "-c", "user.name=E2E"]
    subprocess.run([*git, "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "."], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(
        [*git, "clone", "-q", "--bare", str(repo), str(folder / "monorepo.git")], check=True
    )
    (folder / "clones").mkdir()
    # Migrations and no config, outside any repository: the configuration form creates one.
    bare = folder / "bare" / "sql"
    bare.mkdir(parents=True)
    (bare / "V1_0_0__create_things.sql").write_text(
        "CREATE TABLE things (id INTEGER PRIMARY KEY);\n"
    )
    build_flyway(folder / "flywayapp")


def build_flyway(app: Path) -> None:
    """A Flyway project with no config, whose database Flyway took to version 2."""
    (app / "sql").mkdir(parents=True)
    for number, name in ((1, "a"), (2, "b"), (3, "c")):
        (app / "sql" / f"V{number}__create_{name}.sql").write_text(
            f"CREATE TABLE {name} (id INTEGER PRIMARY KEY);\n"
        )
    (app / "flyway.conf").write_text(
        "flyway.url=jdbc:sqlite:legacy.db\nflyway.user=sa\nflyway.password=hunter2\n"
        "flyway.locations=filesystem:sql\n"
    )
    database = sqlite3.connect(app / "legacy.db")
    database.executescript("""
        CREATE TABLE a (id INTEGER PRIMARY KEY);
        CREATE TABLE b (id INTEGER PRIMARY KEY);
        CREATE TABLE flyway_schema_history (
            installed_rank INT PRIMARY KEY, version VARCHAR(50), description VARCHAR(200), type VARCHAR(20),
            script VARCHAR(1000), checksum INT, installed_by VARCHAR(100),
            installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, execution_time INT, success BOOLEAN
        );
        INSERT INTO flyway_schema_history VALUES (1, '1', 'create a', 'SQL', 'V1__create_a.sql', 123, 'fw', '2026-01-01 10:00:00', 5, 1);
        INSERT INTO flyway_schema_history VALUES (2, '2', 'create b', 'SQL', 'V2__create_b.sql', 456, 'fw', '2026-01-02 10:00:00', 5, 1);
        """)
    database.commit()
    database.close()


def main() -> None:
    port = int(sys.argv[1])
    if len(sys.argv) > 2:
        build_fixtures(Path(sys.argv[2]))
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
