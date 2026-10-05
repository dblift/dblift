def test_list_is_empty_at_first(client, auth):
    assert client.get("/api/projects", headers=auth).json() == []


def test_add_then_list(client, auth, sqlite_project):
    created = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "shop"
    assert body["environments"] == ["staging"]
    assert body["error"] is None

    listed = client.get("/api/projects", headers=auth).json()
    assert [p["id"] for p in listed] == [body["id"]]


def test_add_missing_file_is_a_400(client, auth, tmp_path):
    response = client.post(
        "/api/projects", headers=auth, json={"name": "x", "config_path": str(tmp_path / "no.yaml")}
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


def test_delete(client, auth, sqlite_project):
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]

    assert client.delete(f"/api/projects/{project_id}", headers=auth).status_code == 204
    assert client.get("/api/projects", headers=auth).json() == []
    assert client.delete(f"/api/projects/{project_id}", headers=auth).status_code == 404


def test_unreadable_config_is_reported_not_raised(client, auth, sqlite_project):
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]
    sqlite_project.write_text("database: [unclosed")

    listed = client.get("/api/projects", headers=auth).json()

    assert listed[0]["id"] == project_id
    assert listed[0]["environments"] == []
    assert listed[0]["error"]


def test_config_that_is_not_a_mapping_is_reported(client, auth, sqlite_project):
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]
    sqlite_project.write_text("- just\n- a list\n")

    response = client.get("/api/projects", headers=auth)

    assert response.status_code == 200
    listed = response.json()
    assert listed[0]["id"] == project_id
    assert listed[0]["environments"] == []
    assert listed[0]["error"]


def test_environments_that_is_not_a_mapping_is_reported(client, auth, sqlite_project):
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]
    sqlite_project.write_text("database:\n  type: sqlite\nenvironments:\n  - staging\n")

    response = client.get("/api/projects", headers=auth)

    assert response.status_code == 200
    listed = response.json()
    assert listed[0]["id"] == project_id
    assert listed[0]["environments"] == []
    assert listed[0]["error"]


def test_damaged_registry_file_is_a_500_naming_the_file(client, auth, registry):
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text("{not json")

    response = client.get("/api/projects", headers=auth)

    assert response.status_code == 500
    assert str(registry.path) in response.json()["detail"]


def test_add_with_a_damaged_registry_file_is_a_500(client, auth, registry, sqlite_project):
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text("{not json")

    response = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    )

    assert response.status_code == 500
    assert str(registry.path) in response.json()["detail"]


def test_engine_comes_from_database_type(client, auth, sqlite_project):
    body = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()
    assert body["engine"] == "sqlite"


def test_engine_falls_back_to_the_url_scheme(client, auth, sqlite_project):
    sqlite_project.write_text(
        "database:\n"
        "  url: postgresql+psycopg://db.local:5432/shop\n"
        "  schema: public\n"
        "migrations:\n"
        "  directory: ./migrations\n"
    )
    body = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()
    assert body["engine"] == "postgresql"


def test_engine_is_empty_when_unknown(client, auth, sqlite_project):
    sqlite_project.write_text("migrations:\n  directory: ./migrations\n")
    body = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()
    assert body["engine"] == ""


def test_patch_remembers_the_environment(client, auth, sqlite_project):
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    ).json()["id"]

    patched = client.patch(
        f"/api/projects/{project_id}", headers=auth, json={"last_environment": "staging"}
    )

    assert patched.status_code == 200
    assert patched.json()["last_environment"] == "staging"
    assert client.get("/api/projects", headers=auth).json()[0]["last_environment"] == "staging"


def test_patch_unknown_project_is_a_404(client, auth):
    response = client.patch("/api/projects/nope", headers=auth, json={"last_environment": "x"})
    assert response.status_code == 404
