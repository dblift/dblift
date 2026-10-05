from dblift_ui.server import create_app
from fastapi.testclient import TestClient


def _client(port, token, registry, app_dir):
    app = create_app(token=token, port=port, registry=registry, app_dir=app_dir)
    return TestClient(app, base_url=f"http://127.0.0.1:{port}")


def _built_app(root):
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>built app</title>")
    (root / "assets" / "index-abc.js").write_text("console.log('app')")
    (root / "secret.txt").write_text("not an asset")
    return root


def test_built_app_is_served_when_present(port, token, registry, tmp_path):
    client = _client(port, token, registry, _built_app(tmp_path / "app"))

    assert "built app" in client.get("/").text
    asset = client.get("/assets/index-abc.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text


def test_placeholder_is_served_without_a_build(port, token, registry, tmp_path):
    client = _client(port, token, registry, tmp_path / "missing")

    assert "DBLift UI" in client.get("/").text
    assert client.get("/assets/index-abc.js").status_code == 404


def test_assets_route_cannot_leave_the_assets_folder(port, token, registry, tmp_path):
    client = _client(port, token, registry, _built_app(tmp_path / "app"))

    assert client.get("/assets/%2e%2e/secret.txt").status_code == 404
    assert client.get("/assets/%2e%2e/index.html").status_code == 404


def test_assets_still_require_the_right_host(port, token, registry, tmp_path):
    app = create_app(
        token=token, port=port, registry=registry, app_dir=_built_app(tmp_path / "app")
    )
    foreign = TestClient(app, base_url="http://attacker.example")

    assert foreign.get("/assets/index-abc.js").status_code == 403


def test_unresolvable_asset_path_is_a_404(port, token, registry, tmp_path):
    client = _client(port, token, registry, _built_app(tmp_path / "app"))

    assert client.get("/assets/a%00b").status_code == 404
