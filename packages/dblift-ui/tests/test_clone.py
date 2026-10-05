import subprocess

import pytest
from dblift_ui.clone import CloneError, check_url, clone, folder_name


def _source(tmp_path, name="shop-api"):
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    (work / "dblift.yaml").write_text("database:\n  type: sqlite\n  path: ./dev.db\n")
    for args in (
        ["add", "."],
        ["-c", "user.email=d@e.x", "-c", "user.name=Dev", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(work), *args], check=True)
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(bare)], check=True)
    return bare


def test_clones_into_a_folder_named_after_the_repository(tmp_path):
    bare = _source(tmp_path)
    parent = tmp_path / "projects"

    target = clone(str(bare), str(parent))

    assert target == (parent / "shop-api").resolve()
    assert (target / "dblift.yaml").is_file()


def test_refuses_to_overwrite_an_existing_folder(tmp_path):
    bare = _source(tmp_path)
    parent = tmp_path / "projects"
    (parent / "shop-api").mkdir(parents=True)

    with pytest.raises(CloneError, match="already exists"):
        clone(str(bare), str(parent))


def test_a_failed_clone_leaves_nothing_behind(tmp_path):
    parent = tmp_path / "projects"

    with pytest.raises(CloneError):
        clone(str(tmp_path / "missing.git"), str(parent))
    with pytest.raises(CloneError):
        clone("file://" + str(tmp_path / "also-missing.git"), str(parent))

    assert not parent.exists() or list(parent.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "--upload-pack=touch /tmp/pwned",
        "-oProxyCommand=evil",
        "ext::sh -c 'touch /tmp/pwned'",
        "ext::sh%20-c%20id",
        "http://example.com/acme/shop.git",
        "git://example.com/acme/shop.git",
        "ftp://example.com/shop.git",
        "https://example.com/acme/shop.git with space",
        "https://example.com/acme/shop.git\n--upload-pack=x",
        "relative/path",
        "javascript:alert(1)",
    ],
)
def test_refuses_dangerous_or_unsupported_urls(url):
    with pytest.raises(CloneError):
        check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/shop-api.git",
        "https://github.com/acme/shop-api",
        "ssh://git@github.com/acme/shop-api.git",
        "git@github.com:acme/shop-api.git",
    ],
)
def test_accepts_the_usual_forms(url):
    assert check_url(f"  {url}  ") == url
    assert folder_name(url) == "shop-api"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com/.git",
        "https://example.com/..",
        "git@host:.hidden.git",
    ],
)
def test_refuses_urls_without_a_usable_folder_name(url):
    with pytest.raises(CloneError):
        folder_name(url)


def test_parent_must_be_an_absolute_path(tmp_path):
    with pytest.raises(CloneError, match="full path"):
        clone(str(_source(tmp_path)), "projects")


def test_error_text_does_not_carry_credentials(tmp_path):
    with pytest.raises(CloneError) as raised:
        clone("https://user:s3cret-token@localhost:1/acme/shop.git", str(tmp_path / "projects"))

    assert "s3cret-token" not in str(raised.value)


def test_error_text_does_not_carry_a_token_given_as_the_user_name(tmp_path, monkeypatch):
    url = "https://s3cret-token@localhost:1/acme/shop.git"

    def failing_git(args, **kwargs):
        stderr = f"fatal: repository '{url}/' not found\n".encode()
        return subprocess.CompletedProcess(args, 128, b"", stderr)

    monkeypatch.setattr("dblift_ui.clone.subprocess.run", failing_git)

    with pytest.raises(CloneError) as raised:
        clone(url, str(tmp_path / "projects"))

    assert "s3cret-token" not in str(raised.value)
    assert "https://localhost:1/acme/shop.git" in str(raised.value)


def test_git_missing_is_explained(tmp_path, monkeypatch):
    monkeypatch.setattr("dblift_ui.clone.shutil.which", lambda name: None)

    with pytest.raises(CloneError, match="git is not installed"):
        clone("https://github.com/acme/shop-api.git", str(tmp_path))
