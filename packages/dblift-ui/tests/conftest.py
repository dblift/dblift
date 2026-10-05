from pathlib import Path
from typing import Callable

import pytest
from dblift_ui.registry import ProjectRegistry
from dblift_ui.server import TOKEN_HEADER, create_app
from fastapi.testclient import TestClient

PORT = 8765
TOKEN = "test-token"


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
