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
