"""Serve the interface with seeded SQLite projects, for the browser tests only.

A second argument names a folder where fixture repositories are built for the tests
that add projects, and for the git and new-change tests, whose repositories are also
seeded projects.
"""

import contextlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

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
    build_gitapp(folder / "gitapp", folder / "gitapp.git")
    build_wizardapp(folder / "wizardapp", folder / "wizardapp.git")
    build_wizardhub(folder / "wizardhub", folder / "wizardhub.git")


SQLITE_CONFIG = (
    "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"
)


def build_repository(app: Path, files: dict[str, str], remote: Path) -> Callable[..., None]:
    """A repository on main holding *files* in one commit, with a local bare repository as origin.

    The identity is in the repository's own config; no template, so no hook, and nothing in the
    config makes git run a program. Returns a function that runs git in the repository.
    """
    for relative, text in {
        **files,
        # SQLite writes a journal beside the database while dblift reads it.
        ".gitignore": "*.db\n*.db-journal\n",
    }.items():
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(app), *args], check=True)

    subprocess.run(["git", "init", "-q", "--template=", "-b", "main", str(app)], check=True)
    git("config", "user.email", "e2e@example.com")
    git("config", "user.name", "E2E")
    git("config", "commit.gpgsign", "false")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    subprocess.run(
        ["git", "init", "-q", "--bare", "--template=", "-b", "main", str(remote)], check=True
    )
    git("remote", "add", "origin", str(remote))
    git("push", "-q", "-u", "origin", "main")
    return git


def build_gitapp(app: Path, remote: Path) -> None:
    """A repository on main, with a local bare remote that also holds feature/reporting."""
    git = build_repository(
        app,
        {
            "dblift.yaml": SQLITE_CONFIG,
            "migrations/V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
        },
        remote,
    )
    # A branch that exists only on the remote, with a second config.
    git("switch", "-q", "-c", "feature/reporting")
    (app / "reporting" / "migrations").mkdir(parents=True)
    (app / "reporting" / "dblift.yaml").write_text(SQLITE_CONFIG)
    (app / "reporting" / "migrations" / "V1_0_0__create_reports.sql").write_text(
        "CREATE TABLE reports (id INTEGER PRIMARY KEY);\n"
    )
    git("add", ".")
    git("commit", "-q", "-m", "reporting")
    git("push", "-q", "origin", "feature/reporting")
    git("switch", "-q", "main")
    git("branch", "-q", "-D", "feature/reporting")


def build_wizardapp(app: Path, remote: Path) -> None:
    """The new-change wizard's repository: on main, one migration with its undo script, applied nowhere."""
    build_repository(
        app,
        {
            "dblift.yaml": SQLITE_CONFIG,
            "migrations/V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
            "migrations/U1_0_0__create_accounts.sql": "DROP TABLE accounts;\n",
        },
        remote,
    )


def build_wizardhub(app: Path, remote: Path) -> None:
    """A repository on feature/add-invoices whose origin is a GitHub address, never contacted.

    Only its pull-request link is read. Pushes would go to the local bare repository, should a
    test ever push, and nothing in the tests fetches.
    """
    git = build_repository(
        app,
        {
            "dblift.yaml": SQLITE_CONFIG,
            "migrations/V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
        },
        remote,
    )
    git("remote", "set-url", "origin", "https://github.com/example-org/example-repo.git")
    git("config", "remote.origin.pushurl", str(remote))
    git("switch", "-q", "-c", "feature/add-invoices")


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
        if len(sys.argv) > 2:
            for name in ("gitapp", "wizardapp", "wizardhub"):
                registry.add(name, str(Path(sys.argv[2]) / name / "dblift.yaml"))
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
