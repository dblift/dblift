import json
import sqlite3

CONFIG = "database:\n  type: sqlite\n  path: ./legacy.db\nmigrations:\n  directory: ./sql\n"


def _legacy(tmp_path, table="flyway_schema_history", conf=True):
    root = tmp_path / "legacy"
    (root / "sql").mkdir(parents=True)
    for number, name in ((1, "a"), (2, "b"), (3, "c")):
        (root / "sql" / f"V{number}__create_{name}.sql").write_text(
            f"CREATE TABLE {name} (id INTEGER PRIMARY KEY);\n"
        )
    database = sqlite3.connect(root / "legacy.db")
    database.executescript(f"""
        CREATE TABLE a (id INTEGER PRIMARY KEY);
        CREATE TABLE b (id INTEGER PRIMARY KEY);
        CREATE TABLE {table} (
            installed_rank INT PRIMARY KEY, version VARCHAR(50), description VARCHAR(200), type VARCHAR(20),
            script VARCHAR(1000), checksum INT, installed_by VARCHAR(100),
            installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP, execution_time INT, success BOOLEAN
        );
        INSERT INTO {table} VALUES (1, '1', 'create a', 'SQL', 'V1__create_a.sql', 123, 'fw', '2026-01-01 10:00:00', 5, 1);
        INSERT INTO {table} VALUES (2, '2', 'create b', 'SQL', 'V2__create_b.sql', 456, 'fw', '2026-01-02 10:00:00', 5, 1);
        """)
    database.commit()
    database.close()
    if conf:
        extra = "" if table == "flyway_schema_history" else f"flyway.table={table}\n"
        (root / "flyway.conf").write_text(
            "flyway.url=jdbc:sqlite:legacy.db\nflyway.user=sa\nflyway.password=hunter2\n"
            "flyway.locations=filesystem:sql\n" + extra
        )
    (root / "dblift.yaml").write_text(CONFIG)
    return root


def _run(client, auth, project_id, command, params=None):
    started = client.post(
        f"/api/projects/{project_id}/jobs",
        headers=auth,
        json={"command": command, "params": params or {}},
    )
    assert started.status_code == 202, started.text
    with client.stream(
        "GET", f"/api/jobs/{started.json()['job_id']}/events", headers=auth
    ) as stream:
        lines = [line for line in stream.iter_lines() if line.startswith("data:")]
    return json.loads(lines[-1][5:])["result"]


def _add(client, auth, root):
    return client.post(
        "/api/projects",
        headers=auth,
        json={"name": "legacy", "config_path": str(root / "dblift.yaml")},
    ).json()


def test_read_a_flyway_project(client, auth, tmp_path):
    root = _legacy(tmp_path)

    response = client.post(
        "/api/flyway/read", headers=auth, json={"root": str(root), "path": "flyway.conf"}
    )

    assert response.status_code == 200
    assert "hunter2" not in response.text
    body = response.json()
    assert body["folder"] == str(root.resolve()) and body["table"] == "flyway_schema_history"
    assert body["form"]["engine"] == "sqlite"
    assert body["form"]["connection"]["path"] == "./legacy.db"
    assert body["form"]["migrations_directory"] == "./sql"


def test_read_refusals_are_400(client, auth, tmp_path):
    root = _legacy(tmp_path)

    response = client.post(
        "/api/flyway/read", headers=auth, json={"root": str(root), "path": "dblift.yaml"}
    )

    assert response.status_code == 400 and response.json()["detail"]
    assert (
        client.post("/api/flyway/read", json={"root": str(root), "path": "flyway.conf"}).status_code
        == 401
    )


def test_projects_say_when_a_flyway_file_sits_beside_them(client, auth, tmp_path, sqlite_project):
    legacy = _add(client, auth, _legacy(tmp_path, table="schema_version"))
    plain = client.post(
        "/api/projects", headers=auth, json={"name": "plain", "config_path": str(sqlite_project)}
    ).json()

    assert legacy["flyway_table"] == "schema_version"
    assert plain["flyway_table"] is None


def test_a_missing_config_has_no_flyway_table(client, auth, tmp_path):
    root = _legacy(tmp_path)
    project = _add(client, auth, root)
    (root / "dblift.yaml").unlink()

    listed = client.get("/api/projects", headers=auth).json()

    assert [p["flyway_table"] for p in listed if p["id"] == project["id"]] == [None]


def test_preview_then_import_the_history(client, auth, tmp_path):
    project = _add(client, auth, _legacy(tmp_path))

    preview = _run(
        client, auth, project["id"], "flyway_preview", {"table": "flyway_schema_history"}
    )
    assert preview["success"] is True
    assert preview["message"] == "2 entries would be imported from flyway_schema_history"
    assert preview["has_log"] is True
    before = _run(client, auth, project["id"], "info")
    assert [m["status"] for m in before["migrations"]] == ["PENDING", "PENDING", "PENDING"]

    done = _run(client, auth, project["id"], "flyway_import", {"table": "flyway_schema_history"})
    assert (
        done["success"] is True
        and done["message"] == "2 entries imported from flyway_schema_history"
    )

    after = _run(client, auth, project["id"], "info")
    assert [(m["version"], m["status"]) for m in after["migrations"]] == [
        ("1", "SUCCESS"),
        ("2", "SUCCESS"),
        ("3", "PENDING"),
    ]


def test_a_custom_history_table(client, auth, tmp_path):
    project = _add(client, auth, _legacy(tmp_path, table="schema_version"))

    preview = _run(client, auth, project["id"], "flyway_preview", {"table": "schema_version"})

    assert preview["message"] == "2 entries would be imported from schema_version"


def test_no_flyway_table_is_a_failure_with_its_reason(client, auth, tmp_path):
    project = _add(client, auth, _legacy(tmp_path))

    result = _run(client, auth, project["id"], "flyway_preview", {"table": "nowhere"})

    assert result["success"] is False and "nowhere" in result["error"]


def test_a_bad_table_name_is_refused_before_anything_runs(client, auth, tmp_path):
    project = _add(client, auth, _legacy(tmp_path))

    for table in ("x; DROP TABLE a", "a b", "", "1abc", "a" * 200):
        response = client.post(
            f"/api/projects/{project['id']}/jobs",
            headers=auth,
            json={"command": "flyway_import", "params": {"table": table}},
        )
        assert response.status_code == 400, table


def test_other_results_have_no_message(client, auth, tmp_path):
    project = _add(client, auth, _legacy(tmp_path))

    assert _run(client, auth, project["id"], "info")["message"] is None
