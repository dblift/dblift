from urllib.parse import parse_qs, urlsplit

import pytest
from dblift_ui import gitops

TITLE = "a&b #c?d"
TITLE_ENCODED = "a%26b%20%23c%3Fd"
BODY = "x\n</script>é"
BODY_ENCODED = "x%0A%3C%2Fscript%3E%C3%A9"


def _web(repo, url):
    repo.git("remote", "set-url", "origin", url)
    return gitops.remote_web(repo)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://github.com/acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("https://github.com/acme/shop", ("github", "https://github.com/acme/shop")),
        ("https://github.com/acme/shop.git/", ("github", "https://github.com/acme/shop")),
        ("https://dev@github.com/acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("ssh://git@github.com/acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("ssh://git@github.com:2222/acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("ssh://github.com/acme/shop", ("github", "https://github.com/acme/shop")),
        ("git@github.com:acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("github.com:acme/shop", ("github", "https://github.com/acme/shop")),
        ("git@GitHub.COM:acme/shop.git", ("github", "https://github.com/acme/shop")),
        ("https://gitlab.com/acme/shop.git", ("gitlab", "https://gitlab.com/acme/shop")),
        (
            "git@gitlab.com:group/sub/shop.git",
            ("gitlab", "https://gitlab.com/group/sub/shop"),
        ),
        (
            "https://gitlab.acme.example/group/sub/shop.git",
            ("gitlab", "https://gitlab.acme.example/group/sub/shop"),
        ),
        ("git@bitbucket.org:acme/shop.git", ("bitbucket", "https://bitbucket.org/acme/shop")),
        (
            "https://dev@bitbucket.org/acme/shop.git",
            ("bitbucket", "https://bitbucket.org/acme/shop"),
        ),
        ("https://git.acme.example/acme/shop.git", ("other", "https://git.acme.example/acme/shop")),
        (
            "https://git.acme.example:8443/acme/shop.git",
            ("other", "https://git.acme.example:8443/acme/shop"),
        ),
        ("https://mygitlab.example/acme/shop", ("other", "https://mygitlab.example/acme/shop")),
        ("https://www.github.com/acme/shop", ("other", "https://www.github.com/acme/shop")),
        ("https://github.com:/acme/shop", ("github", "https://github.com/acme/shop")),
        ("HTTPS://GitHub.com/acme/Shop", ("github", "https://github.com/acme/Shop")),
    ],
)
def test_each_remote_form_gives_its_web_address(repo, url, expected):
    assert _web(repo, url) == expected


def test_credentials_never_reach_the_web_address(repo):
    found = _web(repo, "https://user:hunter2@github.com/acme/shop.git")

    assert found == ("github", "https://github.com/acme/shop")
    assert "hunter2" not in repr(found) and "user" not in repr(found)


def test_an_encoded_password_is_dropped_too(repo):
    found = _web(repo, "https://user:p%40ss%2F@github.com/acme/shop.git")

    assert found == ("github", "https://github.com/acme/shop")


@pytest.mark.parametrize("url", ["file:///srv/git/shop.git", "/srv/git/shop.git", "../shop.git"])
def test_a_local_remote_has_no_web_address(repo, url):
    assert _web(repo, url) is None


def test_the_fixtures_local_bare_remote_has_no_web_address(repo):
    assert gitops.remote_web(repo) is None


def test_no_origin_has_no_web_address(repo):
    repo.git("remote", "remove", "origin")

    assert gitops.remote_web(repo) is None


def test_outside_a_repository_there_is_no_web_address(tmp_path):
    assert gitops.remote_web(tmp_path) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/shop?x=<script>",
        "https://github.com/acme/shop#frag",
        "javascript:alert(1)",
        "https://github.com/acme/../shop",
        "https://github.com/acme/./shop",
        "https://github.com/../acme/shop",
        "https://github.com/acme/my shop",
        "https://github.com/acme%2f..%2fevil/shop",
        "https://github.com/acme%2Fevil/shop",
        "https://github.com//acme/shop",
        "https://github.com/acme",
        "https://github.com/acme/.git",
        "https://evil.example\\@github.com/acme/shop",
        "https://github.com\\@evil.example/acme/shop",
        "https://github.com/acme\\shop/x",
        "https://gіthub.com/acme/shop",  # a Cyrillic i
        "https://[::1]/acme/shop",
        "https://github.com:99999/acme/shop",
        "https://github.com:abc/acme/shop",
        "ssh://git@github.com:acme/shop.git",
        "https://-evil.example/acme/shop",
        "https://github.com./acme/shop",
        "https://github..com/acme/shop",
        "http://github.com/acme/shop",
        "git://github.com/acme/shop.git",
        "ext::sh -c touch% /tmp/x",
        "git@github.com:/acme/shop.git",
        "git@github.com:~acme/shop.git",
        "a@b@github.com:acme/shop",
        "git@github.com:acme/shop\t.git",
        "https://github.com;evil.example/acme/shop",
        "https://github.com%2eevil.example/acme/shop",
        "https://github\uff0ecom/acme/shop",  # a full-width dot
        "ssh://[git@github.com]/acme/shop",
        "https://github.com:443:80/acme/shop",
        "https://github.com/acme/sh@op",
    ],
)
def test_a_hostile_remote_gives_no_web_address(repo, url):
    assert _web(repo, url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com@evil.example/acme/shop",
        "https://github.com%2f@evil.example/acme/shop",
        "https://github.com:443@evil.example/acme/shop",
        "ssh://github.com@evil.example/acme/shop",
        "github.com@evil.example:acme/shop",
    ],
)
def test_a_host_hidden_in_the_user_name_is_not_believed(repo, url):
    assert _web(repo, url) == ("other", "https://evil.example/acme/shop")


def test_a_github_link_is_a_compare_page_with_title_and_body():
    url = gitops.pull_request_url(
        "github", "https://github.com/acme/shop", "feature/add-invoices", TITLE, BODY
    )

    assert url == (
        "https://github.com/acme/shop/compare/feature/add-invoices?expand=1"
        f"&title={TITLE_ENCODED}&body={BODY_ENCODED}"
    )


def test_a_gitlab_link_opens_a_new_merge_request():
    url = gitops.pull_request_url(
        "gitlab", "https://gitlab.com/group/sub/shop", "feature/add-invoices", TITLE, BODY
    )

    assert url == (
        "https://gitlab.com/group/sub/shop/-/merge_requests/new"
        "?merge_request%5Bsource_branch%5D=feature%2Fadd-invoices"
        f"&merge_request%5Btitle%5D={TITLE_ENCODED}"
    )


def test_a_bitbucket_link_opens_a_new_pull_request():
    url = gitops.pull_request_url(
        "bitbucket", "https://bitbucket.org/acme/shop", "feature/add-invoices", TITLE, BODY
    )

    assert url == "https://bitbucket.org/acme/shop/pull-requests/new?source=feature%2Fadd-invoices"


def test_another_host_has_no_link():
    assert (
        gitops.pull_request_url("other", "https://git.acme.example/a/b", "main", TITLE, BODY)
        is None
    )


@pytest.mark.parametrize("kind", ["github", "gitlab", "bitbucket"])
def test_hostile_text_stays_inside_its_parameter(kind):
    title = "x&expand=0#y?z\r\n</script><script>alert(1)</script> é/ \\"
    branch = "feature/a#b?c&d"
    base = "https://example.org/acme/shop"

    url = gitops.pull_request_url(kind, base, branch, title, title)

    parts = urlsplit(url)
    assert parts.scheme == "https" and parts.netloc == "example.org"
    assert parts.fragment == ""
    assert not any(c in url for c in " <>\"'\\\r\n")
    query = parse_qs(parts.query, keep_blank_values=True)
    if kind == "github":
        assert parts.path == "/acme/shop/compare/feature/a%23b%3Fc%26d"
        assert query == {"expand": ["1"], "title": [title], "body": [title]}
    elif kind == "gitlab":
        assert query == {
            "merge_request[source_branch]": [branch],
            "merge_request[title]": [title],
        }
    else:
        assert query == {"source": [branch]}


def test_the_body_is_cut_to_four_thousand_characters():
    url = gitops.pull_request_url("github", "https://github.com/a/b", "main", "t", "é" * 5000)

    assert parse_qs(urlsplit(url).query)["body"] == ["é" * 4000]


@pytest.mark.parametrize(
    "base",
    ["http://github.com/a/b", "javascript:alert(1)//github.com/a/b", "//evil.example/a/b", ""],
)
def test_a_link_is_never_built_on_anything_but_https(base):
    assert gitops.pull_request_url("github", base, "main", "t", "b") is None


# --- the route ----------------------------------------------------------------------


def _add(client, auth, config):
    response = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _ask(client, auth, project_id, title=TITLE, body=BODY):
    return client.post(
        f"/api/projects/{project_id}/git/pull-request",
        headers=auth,
        json={"title": title, "body": body},
    )


def test_the_route_builds_a_github_link(client, auth, repo):
    repo.git("remote", "set-url", "origin", "git@github.com:acme/shop.git")
    repo.git("switch", "-q", "-c", "feature/add-invoices")
    project_id = _add(client, auth, repo / "dblift.yaml")

    response = _ask(client, auth, project_id)

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://github.com/acme/shop/compare/feature/add-invoices?expand=1"
        f"&title={TITLE_ENCODED}&body={BODY_ENCODED}",
        "kind": "github",
        "branch": "feature/add-invoices",
    }


def test_the_route_has_no_link_for_an_unknown_host(client, auth, repo):
    repo.git("remote", "set-url", "origin", "https://git.acme.example/acme/shop.git")
    project_id = _add(client, auth, repo / "dblift.yaml")

    assert _ask(client, auth, project_id).json() == {
        "url": None,
        "kind": "other",
        "branch": "main",
    }


def test_the_route_has_no_link_for_a_local_remote(client, auth, repo):
    project_id = _add(client, auth, repo / "dblift.yaml")

    assert _ask(client, auth, project_id).json() == {"url": None, "kind": None, "branch": "main"}


def test_the_route_never_returns_the_remotes_credentials(client, auth, repo):
    repo.git("remote", "set-url", "origin", "https://dev:hunter2@github.com/acme/shop.git")
    project_id = _add(client, auth, repo / "dblift.yaml")

    response = _ask(client, auth, project_id)

    assert response.json()["url"].startswith("https://github.com/acme/shop/compare/main?")
    assert "hunter2" not in response.text


def test_the_route_refuses_a_detached_head(client, auth, repo):
    repo.git("switch", "-q", "--detach", "HEAD")
    project_id = _add(client, auth, repo / "dblift.yaml")

    response = _ask(client, auth, project_id)

    assert response.status_code == 400 and response.json()["detail"]


def test_the_route_refuses_a_project_outside_a_repository(client, auth, sqlite_project):
    project_id = _add(client, auth, sqlite_project)

    response = _ask(client, auth, project_id)

    assert response.status_code == 400
    assert response.json()["detail"] == "This project is not in a git repository."


def test_the_route_needs_the_token(client):
    response = client.post("/api/projects/x/git/pull-request", json={"title": "", "body": ""})

    assert response.status_code == 401
