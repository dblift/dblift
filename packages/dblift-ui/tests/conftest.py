import subprocess
import threading
from pathlib import Path
from typing import Callable

import pytest
from dblift_ui.jobs import JobRunner
from dblift_ui.registry import ProjectRegistry
from dblift_ui.server import TOKEN_HEADER, create_app
from fastapi.testclient import TestClient

PORT = 8765
TOKEN = "test-token"


@pytest.fixture(autouse=True)
def no_containers(monkeypatch):
    """No test reaches a container runtime unless it asks for one itself."""
    monkeypatch.setenv("DBLIFT_UI_CONTAINER_RUNTIME", "none")


class FakeRuntime:
    """A container runtime that records what it is asked and starts nothing."""

    name = "Fake"

    def __init__(self, present=True):
        self.present = present
        self.pulled = []
        self.started = []
        self.executed = []
        self.removed = []
        self.existing = []
        # Replies to ``execute`` by the command's first word: a list is consumed in order.
        self.replies = {}
        self.stopped = False
        self.output = ""
        self.keeps_containers = False

    def available(self):
        return True

    def has_image(self, image):
        return self.present

    def pull(self, image):
        self.pulled.append(image)
        self.present = True

    def start(self, name, spec, environment):
        self.started.append((name, spec.image, dict(environment)))
        self.existing.append(name)

    def address(self, name, port):
        return "127.0.0.1", port

    def execute(self, name, argv, timeout, stdin=""):
        self.executed.append((list(argv), stdin, timeout))
        reply = self.replies.get(argv[0], (0, ""))
        if isinstance(reply, list):
            reply = reply.pop(0) if len(reply) > 1 else reply[0]
        return reply

    def running(self, name):
        return not self.stopped

    def logs(self, name):
        return self.output

    def remove(self, name):
        self.removed.append(name)
        if not self.keeps_containers and name in self.existing:
            self.existing.remove(name)

    def names(self, prefix):
        return [name for name in self.existing if name.startswith(prefix)]


@pytest.fixture
def fake_runtime():
    """The FakeRuntime class: call it to make one."""
    return FakeRuntime


@pytest.fixture
def port() -> int:
    return PORT


@pytest.fixture
def token() -> str:
    return TOKEN


@pytest.fixture
def auth() -> dict:
    return {TOKEN_HEADER: TOKEN}


@pytest.fixture
def registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(tmp_path / "state" / "projects.json")


@pytest.fixture
def make_client(registry: ProjectRegistry) -> Callable[[str], TestClient]:
    def factory(base_url: str) -> TestClient:
        app = create_app(token=TOKEN, port=PORT, registry=registry)
        return TestClient(app, base_url=base_url)

    return factory


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client(f"http://127.0.0.1:{PORT}")


@pytest.fixture
def sqlite_project(tmp_path: Path) -> Path:
    """A project folder with two pending migrations; returns its config path."""
    project = tmp_path / "shop"
    (project / "migrations").mkdir(parents=True)
    (project / "migrations" / "V1_0_0__create_customers.sql").write_text(
        "CREATE TABLE customers (id INTEGER PRIMARY KEY);\n"
    )
    (project / "migrations" / "V1_0_1__create_orders.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY);\n"
    )
    (project / "migrations" / "U1_0_0__create_customers.sql").write_text("DROP TABLE customers;\n")
    (project / "migrations" / "U1_0_1__create_orders.sql").write_text("DROP TABLE orders;\n")
    config = project / "dblift.yaml"
    config.write_text(
        "database:\n"
        "  type: sqlite\n"
        "  path: ./dev.db\n"
        "migrations:\n"
        "  directory: ./migrations\n"
        "environments:\n"
        "  staging:\n"
        "    database:\n"
        "      path: ./staging.db\n"
    )
    return config


@pytest.fixture
def held_migrate(monkeypatch):
    """Make `migrate` block until released, so a job can be caught mid-run."""
    entered, release = threading.Event(), threading.Event()
    real = JobRunner.COMMANDS["migrate"]

    def slow(client, params):
        entered.set()
        assert release.wait(timeout=10), "test never released the held migrate"
        return real(client, params)

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", slow)
    yield entered, release
    release.set()


@pytest.fixture
def repo(tmp_path):
    """A repository with one commit, an origin, and a second branch on the remote only."""

    def git(cwd, *args):
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=dev@example.com",
                "-c",
                "user.name=Dev",
                "-C",
                str(cwd),
                *args,
            ],
            check=True,
            capture_output=True,
        )

    class Repository(type(tmp_path)):  # a path that can also run git in itself
        def git(self, *args):
            git(self, *args)

    work = Repository(tmp_path / "work")
    (work / "migrations").mkdir(parents=True)
    (work / "dblift.yaml").write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"
    )
    (work / "migrations" / "V1_0_0__create_accounts.sql").write_text(
        "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n"
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    git(work, "config", "user.email", "dev@example.com")
    git(work, "config", "user.name", "Dev")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "init")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    git(work, "remote", "add", "origin", str(bare))
    git(work, "switch", "-q", "-c", "feature/remote-only")
    (work / "migrations" / "V1_1_0__add_emails.sql").write_text(
        "ALTER TABLE accounts ADD email TEXT;\n"
    )
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "emails")
    git(work, "push", "-q", "-u", "origin", "feature/remote-only")
    git(work, "switch", "-q", "main")
    git(work, "branch", "-q", "-D", "feature/remote-only")
    git(work, "push", "-q", "-u", "origin", "main")
    return work


@pytest.fixture
def colleague_pushes(tmp_path, repo):
    """Call it to have someone else push a commit adding *name* to origin's main."""

    def push(name: str = "theirs.txt") -> None:
        other = tmp_path / "other"
        if not other.exists():
            subprocess.run(
                ["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True
            )
        (other / name).write_text("x")
        for args in (
            ["add", "."],
            ["-c", "user.email=c@e.x", "-c", "user.name=Col", "commit", "-q", "-m", name],
            ["push", "-q"],
        ):
            subprocess.run(["git", "-C", str(other), *args], check=True, capture_output=True)

    return push
