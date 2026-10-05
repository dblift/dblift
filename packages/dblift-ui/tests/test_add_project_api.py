import subprocess
from pathlib import Path

CONFIG = "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"


def _repo(root):
    root.mkdir(parents=True)
    (root / "services" / "billing").mkdir(parents=True)
    (root / "dblift.yaml").write_text(CONFIG)
    (root / "services" / "billing" / "dblift.yaml").write_text(CONFIG)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for args in (
        ["add", "."],
        ["-c", "user.email=d@e.x", "-c", "user.name=Dev", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    return root


def test_defaults(client, auth):
    body = client.get("/api/defaults", headers=auth).json()

    assert body["clone_parent"] == str(Path.home() / "dblift-projects")
    assert body["git"] is True


def test_discover_a_folder(client, auth, tmp_path):
    root = _repo(tmp_path / "platform")

    found = client.post("/api/discover", headers=auth, json={"path": str(root)})

    assert found.status_code == 200
    body = found.json()
    assert body["name"] == "platform" and body["repository"] is True and body["branch"] == "main"
    assert [c["path"] for c in body["configs"]] == ["dblift.yaml", "services/billing/dblift.yaml"]
    assert all(c["registered"] is False for c in body["configs"])


def test_discover_marks_what_is_already_added(client, auth, tmp_path):
    root = _repo(tmp_path / "platform")
    client.post(
        "/api/projects",
        headers=auth,
        json={"name": "platform", "config_path": str(root / "dblift.yaml")},
    )

    body = client.post("/api/discover", headers=auth, json={"path": str(root)}).json()

    assert [(c["path"], c["registered"]) for c in body["configs"]] == [
        ("dblift.yaml", True),
        ("services/billing/dblift.yaml", False),
    ]


def test_discover_a_bad_path_is_a_400(client, auth):
    response = client.post("/api/discover", headers=auth, json={"path": "relative"})

    assert response.status_code == 400
    assert response.json()["detail"]


def test_clone_then_discover(client, auth, tmp_path):
    source = _repo(tmp_path / "platform")
    parent = tmp_path / "projects"

    cloned = client.post(
        "/api/clone", headers=auth, json={"url": str(source), "parent": str(parent)}
    )

    assert cloned.status_code == 200
    target = cloned.json()["path"]
    assert target == str((parent / "platform").resolve())
    body = client.post("/api/discover", headers=auth, json={"path": target}).json()
    assert len(body["configs"]) == 2


def test_clone_a_refused_url_is_a_400(client, auth, tmp_path):
    response = client.post(
        "/api/clone", headers=auth, json={"url": "ext::sh -c id", "parent": str(tmp_path)}
    )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_discover_and_clone_need_the_token(client, tmp_path):
    assert client.post("/api/discover", json={"path": str(tmp_path)}).status_code == 401
    assert client.post("/api/clone", json={"url": "x", "parent": str(tmp_path)}).status_code == 401
    assert client.get("/api/defaults").status_code == 401


def test_projects_say_which_repository_they_belong_to(client, auth, tmp_path):
    root = _repo(tmp_path / "platform")
    for name, config in (
        ("root", root / "dblift.yaml"),
        ("billing", root / "services" / "billing" / "dblift.yaml"),
    ):
        client.post("/api/projects", headers=auth, json={"name": name, "config_path": str(config)})

    listed = client.get("/api/projects", headers=auth).json()

    assert {p["repository"] for p in listed} == {"platform"}
    assert {p["repository_path"] for p in listed} == {str(root.resolve())}
    assert all(p["missing"] is False for p in listed)


def test_a_project_outside_git_is_its_own_group(client, auth, sqlite_project):
    client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    )

    project = client.get("/api/projects", headers=auth).json()[0]

    assert project["repository"] == sqlite_project.parent.name
    assert project["repository_path"] == str(sqlite_project.parent.resolve())


def test_a_config_that_disappeared_is_reported_as_missing(client, auth, sqlite_project):
    client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(sqlite_project)}
    )
    sqlite_project.unlink()

    project = client.get("/api/projects", headers=auth).json()[0]

    assert project["missing"] is True
    assert "another branch" in project["error"]
