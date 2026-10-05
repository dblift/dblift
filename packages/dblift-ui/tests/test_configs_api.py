import yaml

SQLITE_FORM = {
    "engine": "sqlite",
    "connection": {"path": "./dev.db", "password": {"mode": "none", "value": ""}},
}
PG_FORM = {
    "engine": "postgresql",
    "connection": {
        "host": "db.example.com",
        "port": 5432,
        "database": "shop",
        "username": "app",
        "schema": "public",
        "password": {"mode": "literal", "value": "s3cret"},
    },
}


def test_engines(client, auth):
    engines = client.get("/api/config/engines", headers=auth).json()

    assert len(engines) == 11
    assert engines[0] == {
        "id": "postgresql",
        "label": "PostgreSQL",
        "scheme": "postgresql",
        "port": 5432,
        "fields": ["host", "port", "database", "username", "password", "schema"],
    }


def test_preview_returns_masked_yaml_and_the_loaders_verdict(client, auth):
    body = client.post("/api/config/preview", headers=auth, json={"form": PG_FORM}).json()

    assert body["problems"] == []
    assert "s3cret" not in body["yaml"]
    assert (
        yaml.safe_load(body["yaml"])["database"]["url"] == "postgresql://db.example.com:5432/shop"
    )


def test_preview_of_a_refused_form_explains(client, auth):
    form = {**PG_FORM, "connection": {**PG_FORM["connection"], "host": ""}}

    response = client.post("/api/config/preview", headers=auth, json={"form": form})

    assert response.status_code == 200
    assert response.json() == {
        "yaml": "",
        "problems": ["the host is required (letters, digits, dots and dashes)"],
        "warnings": [],
    }


def test_create_writes_a_config_and_registers_the_project(client, auth, tmp_path):
    created = client.post(
        "/api/config",
        headers=auth,
        json={
            "folder": str(tmp_path),
            "filename": "dblift.yaml",
            "name": "shop",
            "form": SQLITE_FORM,
        },
    )

    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "shop" and project["engine"] == "sqlite" and project["error"] is None
    assert project["config_path"] == str(tmp_path.resolve() / "dblift.yaml")
    assert [p["id"] for p in client.get("/api/projects", headers=auth).json()] == [project["id"]]


def test_create_refusals_are_400_and_register_nothing(client, auth, tmp_path):
    (tmp_path / "dblift.yaml").write_text("x\n")

    refused = client.post(
        "/api/config",
        headers=auth,
        json={
            "folder": str(tmp_path),
            "filename": "dblift.yaml",
            "name": "shop",
            "form": SQLITE_FORM,
        },
    )

    assert refused.status_code == 400 and "already exists" in refused.json()["detail"]
    assert client.get("/api/projects", headers=auth).json() == []


def _project(client, auth, tmp_path, text):
    config = tmp_path / "dblift.yaml"
    config.write_text(text)
    return (
        client.post(
            "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
        ).json(),
        config,
    )


def test_read_a_projects_config_without_its_password(client, auth, tmp_path):
    project, _ = _project(
        client,
        auth,
        tmp_path,
        "database:\n  url: postgresql://h:5432/shop\n  username: app\n  password: hunter2\n",
    )

    response = client.get(f"/api/projects/{project['id']}/config", headers=auth)

    assert response.status_code == 200
    assert "hunter2" not in response.text
    body = response.json()
    assert body["form"]["connection"]["password"] == {"mode": "keep", "value": ""}
    assert body["form"]["connection"]["schema"] == ""
    assert len(body["revision"]) == 64 and body["notes"] == []


def test_the_preview_of_a_project_hides_every_stored_secret(client, auth, tmp_path):
    project, _ = _project(
        client,
        auth,
        tmp_path,
        "database:\n  url: postgresql://h:5432/shop\n  username: app\n  password: hunter2\n"
        "  account_key: key-hunter3\n"
        "  properties:\n    sslpassword: ssl-hunter4\n"
        "  extra_params:\n    dsn: odbc://u:dsn-hunter5@h/x\n"
        "secrets:\n  provider: vault\n  token: tok-hunter6\n",
    )
    read = client.get(f"/api/projects/{project['id']}/config", headers=auth).json()

    response = client.post(
        "/api/config/preview",
        headers=auth,
        json={"form": read["form"], "project_id": project["id"]},
    )

    assert response.status_code == 200
    assert "hunter" not in response.text
    assert yaml.safe_load(response.json()["yaml"])["secrets"]["provider"] == "vault"


def test_update_a_projects_config(client, auth, tmp_path):
    project, config = _project(
        client,
        auth,
        tmp_path,
        "# mine\ndatabase:\n  url: postgresql://h:5432/shop\n  username: app\n  password: hunter2\n",
    )
    read = client.get(f"/api/projects/{project['id']}/config", headers=auth).json()
    read["form"]["connection"]["host"] = "other"
    read["form"]["environments"] = [
        {
            "name": "staging",
            "connection": {
                "host": "stg",
                "port": 5432,
                "database": "shop",
                "password": {"mode": "keep", "value": ""},
            },
        }
    ]

    refused = client.put(
        f"/api/projects/{project['id']}/config",
        headers=auth,
        json={"form": read["form"], "revision": read["revision"]},
    )
    assert refused.status_code == 400 and "no saved password" in refused.json()["detail"]

    read["form"]["environments"][0]["connection"]["password"] = {"mode": "env", "value": "STG_PW"}
    saved = client.put(
        f"/api/projects/{project['id']}/config",
        headers=auth,
        json={"form": read["form"], "revision": read["revision"]},
    )

    assert saved.status_code == 200
    assert saved.json()["environments"] == ["staging"]
    text = config.read_text()
    assert (
        text.startswith("# mine\n") and "postgresql://other:5432/shop" in text and "hunter2" in text
    )


def test_a_stale_revision_is_a_409(client, auth, tmp_path):
    project, config = _project(
        client, auth, tmp_path, "database:\n  type: sqlite\n  path: ./dev.db\n"
    )
    read = client.get(f"/api/projects/{project['id']}/config", headers=auth).json()
    config.write_text(config.read_text() + "# touched\n")

    response = client.put(
        f"/api/projects/{project['id']}/config",
        headers=auth,
        json={"form": read["form"], "revision": read["revision"]},
    )

    assert response.status_code == 409 and "changed" in response.json()["detail"]


def test_a_config_that_cannot_be_read_as_one_is_a_400(client, auth, tmp_path):
    project, _ = _project(client, auth, tmp_path, "- not\n- a config\n")

    assert client.get(f"/api/projects/{project['id']}/config", headers=auth).status_code == 400


def test_unknown_project_and_missing_token(client, auth):
    assert client.get("/api/projects/nope/config", headers=auth).status_code == 404
    assert client.get("/api/config/engines").status_code == 401
    assert client.post("/api/config/preview", json={"form": SQLITE_FORM}).status_code == 401
    assert client.post("/api/config", json={}).status_code == 401
