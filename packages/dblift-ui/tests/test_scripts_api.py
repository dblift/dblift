import json
import threading

import pytest
from dblift_ui.jobs import JobRunner
from dblift_ui.scripts import ScriptStore


@pytest.fixture
def project_id(client, auth, sqlite_project):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]


def _finish(client, auth, project_id, command):
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": command}
    ).json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        return [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")][-1][
            "result"
        ]


def test_list_scripts(client, auth, project_id):
    listed = client.get(f"/api/projects/{project_id}/scripts", headers=auth)

    assert listed.status_code == 200
    first = listed.json()[0]
    assert first == {
        "name": "V1_0_0__create_customers.sql",
        "kind": "versioned",
        "version": "1.0.0",
        "description": "create_customers",
        "language": "sql",
        "directory": "migrations",
        "has_undo": True,
    }


def test_read_a_script_and_its_undo(client, auth, project_id):
    script = client.get(
        f"/api/projects/{project_id}/scripts/V1_0_0__create_customers.sql", headers=auth
    )
    undo = client.get(
        f"/api/projects/{project_id}/scripts/U1_0_0__create_customers.sql", headers=auth
    )

    assert script.json()["content"] == "CREATE TABLE customers (id INTEGER PRIMARY KEY);\n"
    assert script.json()["kind"] == "versioned"
    assert undo.json()["content"] == "DROP TABLE customers;\n"
    assert undo.json()["kind"] == "undo"


def test_save_a_script(client, auth, project_id, sqlite_project):
    response = client.put(
        f"/api/projects/{project_id}/scripts/V1_0_1__create_orders.sql",
        headers=auth,
        json={"content": "CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER);\n"},
    )

    assert response.status_code == 200
    on_disk = (sqlite_project.parent / "migrations" / "V1_0_1__create_orders.sql").read_text()
    assert on_disk == "CREATE TABLE orders (id INTEGER PRIMARY KEY, total INTEGER);\n"


def test_unknown_script_and_project_are_404(client, auth, project_id):
    assert (
        client.get(f"/api/projects/{project_id}/scripts/V9_9_9__nope.sql", headers=auth).status_code
        == 404
    )
    assert client.get("/api/projects/nope/scripts", headers=auth).status_code == 404
    assert (
        client.get(
            "/api/projects/nope/scripts/V1_0_0__create_customers.sql", headers=auth
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "name", ["dblift.yaml", "dev.db", "%2e%2e%2fdblift.yaml", "V1_0_0__create_customers.sh"]
)
def test_the_scripts_api_serves_scripts_only(client, auth, project_id, name):
    read = client.get(f"/api/projects/{project_id}/scripts/{name}", headers=auth)
    write = client.put(
        f"/api/projects/{project_id}/scripts/{name}", headers=auth, json={"content": "x"}
    )

    assert read.status_code in (400, 404)
    assert write.status_code in (400, 404)


def test_the_config_is_never_overwritten_through_the_scripts_api(
    client, auth, project_id, sqlite_project
):
    before = sqlite_project.read_text()

    client.put(
        f"/api/projects/{project_id}/scripts/%2e%2e%2fdblift.yaml",
        headers=auth,
        json={"content": "x"},
    )
    client.put(
        f"/api/projects/{project_id}/scripts/dblift.yaml", headers=auth, json={"content": "x"}
    )

    assert sqlite_project.read_text() == before


def test_scripts_routes_need_the_token(client, project_id):
    assert client.get(f"/api/projects/{project_id}/scripts").status_code == 401
    assert (
        client.put(
            f"/api/projects/{project_id}/scripts/V1_0_0__create_customers.sql",
            json={"content": "x"},
        ).status_code
        == 401
    )


def test_create_then_see_it_pending(client, auth, project_id, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    created = client.post(
        f"/api/projects/{project_id}/scripts",
        headers=auth,
        json={"kind": "versioned", "language": "sql", "description": "add invoices"},
    )

    assert created.status_code == 201
    assert created.json() == {"created": ["V1_0_2__add_invoices.sql", "U1_0_2__add_invoices.sql"]}
    status = _finish(client, auth, project_id, "info")
    assert ("1.0.2", "PENDING") in [(m["version"], m["status"]) for m in status["migrations"]]


def test_create_with_a_bad_request_is_a_400(client, auth, project_id):
    response = client.post(
        f"/api/projects/{project_id}/scripts",
        headers=auth,
        json={"kind": "versioned", "language": "sql", "description": "  "},
    )
    assert response.status_code == 400
    assert response.json()["detail"]


def test_saving_is_refused_while_a_change_runs(client, auth, project_id, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    entered, release = threading.Event(), threading.Event()
    real = JobRunner.COMMANDS["migrate"]

    def slow(client_, params):
        entered.set()
        assert release.wait(timeout=10)
        return real(client_, params)

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", slow)
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    ).json()["job_id"]
    assert entered.wait(timeout=10)
    try:
        refused = client.put(
            f"/api/projects/{project_id}/scripts/V1_0_1__create_orders.sql",
            headers=auth,
            json={"content": "SELECT 1;\n"},
        )
        reading = client.get(
            f"/api/projects/{project_id}/scripts/V1_0_1__create_orders.sql", headers=auth
        )
    finally:
        release.set()
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        list(response.iter_lines())

    assert refused.status_code == 409
    assert reading.status_code == 200


# Beyond the brief: names that do reach the store over HTTP are refused by its name check.
# (``%2e%2e%2f...`` never does: the router decodes it to a path with a ``/`` and answers 404.)


@pytest.mark.parametrize(
    "name",
    ["dblift.yaml", "dev.db", "%2e%2e", "V1_0_0__x.sh", "V1_0_0__create_customers.sql%0A"],
)
def test_names_reaching_the_store_are_refused_by_it(client, auth, project_id, name, monkeypatch):
    received = []
    real = ScriptStore._find

    def spy(script_name, files):
        received.append(script_name)
        return real(script_name, files)

    monkeypatch.setattr(ScriptStore, "_find", staticmethod(spy))
    read = client.get(f"/api/projects/{project_id}/scripts/{name}", headers=auth)
    write = client.put(
        f"/api/projects/{project_id}/scripts/{name}", headers=auth, json={"content": "x"}
    )

    assert received, f"{name!r} never reached the store"
    assert (read.status_code, write.status_code) == (400, 400)
    assert read.json()["detail"] == "not a script name"


# Review fixes.


def test_creating_is_refused_while_a_change_runs(
    client, auth, project_id, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    migrations = sqlite_project.parent / "migrations"
    before = sorted(p.name for p in migrations.iterdir())
    entered, release = threading.Event(), threading.Event()
    real = JobRunner.COMMANDS["migrate"]

    def slow(client_, params):
        entered.set()
        assert release.wait(timeout=10)
        return real(client_, params)

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", slow)
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    ).json()["job_id"]
    assert entered.wait(timeout=10)
    try:
        creating = client.post(
            f"/api/projects/{project_id}/scripts",
            headers=auth,
            json={"kind": "versioned", "language": "sql", "description": "add invoices"},
        )
        saving = client.put(
            f"/api/projects/{project_id}/scripts/V1_0_1__create_orders.sql",
            headers=auth,
            json={"content": "SELECT 1;\n"},
        )
        listed = sorted(p.name for p in migrations.iterdir())
    finally:
        release.set()
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        list(response.iter_lines())

    assert creating.status_code == 409
    assert creating.json()["detail"] == saving.json()["detail"]
    assert listed == before


def test_a_huge_migrations_directory_is_a_400_and_nothing_is_written(
    client, auth, project_id, sqlite_project, monkeypatch
):
    monkeypatch.setattr("dblift_ui.scripts.MAX_ENTRIES", 3)
    migrations = sqlite_project.parent / "migrations"
    before = {p.name: p.read_text() for p in migrations.iterdir()}
    base = f"/api/projects/{project_id}/scripts"

    responses = [
        client.get(base, headers=auth),
        client.get(f"{base}/V1_0_0__create_customers.sql", headers=auth),
        client.put(
            f"{base}/V1_0_0__create_customers.sql", headers=auth, json={"content": "SELECT 2;\n"}
        ),
        client.post(
            base, headers=auth, json={"kind": "versioned", "language": "sql", "description": "x"}
        ),
    ]

    for response in responses:
        assert response.status_code == 400
        assert response.json()["detail"].startswith(
            "the migrations directory holds too many files to list here"
        )
    assert {p.name: p.read_text() for p in migrations.iterdir()} == before


def test_config_errors_never_quote_the_config(client, auth, sqlite_project):
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n  password: s3cret-value: oops\n"
    )
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]

    listed = client.get("/api/projects", headers=auth).json()[0]["error"]
    scripts = client.get(f"/api/projects/{project_id}/scripts", headers=auth)

    assert scripts.status_code == 400
    for error in (listed, scripts.json()["detail"]):
        assert "line" in error
        assert "s3cret-value" not in error
