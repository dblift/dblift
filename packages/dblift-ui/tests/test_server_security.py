from dblift_ui import __version__
from dblift_ui.server import TOKEN_HEADER


def test_health_with_token(client, auth):
    response = client.get("/api/health", headers=auth)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_api_without_token_is_rejected(client):
    assert client.get("/api/health").status_code == 401


def test_api_with_wrong_token_is_rejected(client):
    assert client.get("/api/health", headers={TOKEN_HEADER: "nope"}).status_code == 401


def test_foreign_host_is_rejected_even_with_token(make_client, auth):
    rebinding = make_client("http://attacker.example")
    assert rebinding.get("/api/health", headers=auth).status_code == 403


def test_localhost_name_is_accepted(make_client, port, auth):
    by_name = make_client(f"http://localhost:{port}")
    assert by_name.get("/api/health", headers=auth).status_code == 200


def test_wrong_port_in_host_is_rejected(make_client, auth):
    other = make_client("http://127.0.0.1:9999")
    assert other.get("/api/health", headers=auth).status_code == 403


def test_cross_origin_write_is_rejected(client, auth):
    response = client.post(
        "/api/projects", headers={**auth, "Origin": "https://evil.example"}, json={}
    )
    assert response.status_code == 403


def test_same_origin_write_passes_the_guard(client, port, auth):
    response = client.post(
        "/api/projects", headers={**auth, "Origin": f"http://127.0.0.1:{port}"}, json={}
    )
    assert response.status_code != 403


def test_index_page_needs_no_token(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "DBLift UI" in response.text
