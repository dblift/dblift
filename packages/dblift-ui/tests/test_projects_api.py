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
