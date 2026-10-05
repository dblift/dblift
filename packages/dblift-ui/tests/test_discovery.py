import os
import subprocess

import pytest
from dblift_ui import discovery
from dblift_ui.discovery import DiscoveryError, discover

CONFIG = "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"


def _write(root, relative, text="x"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "dev@example.com")
    _git(root, "config", "user.name", "Dev")
    return root


def _kinds(found):
    return [(c.path, c.kind) for c in found.configs]


def test_finds_a_config_and_reports_the_folder(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", CONFIG)
    _write(root, "migrations/V1_0_0__a.sql")

    found = discover(str(root))

    assert (found.root, found.name) == (str(root.resolve()), "shop")
    assert found.repository is False and found.branch == ""
    assert _kinds(found) == [("dblift.yaml", "named")]
    assert found.configs[0].problem is None
    assert found.script_folders == []
    assert found.truncated is False


def test_monorepo_with_several_configs(tmp_path):
    root = tmp_path / "platform"
    _write(root, "services/billing/dblift.yaml", CONFIG)
    _write(root, "services/billing/migrations/V1__a.sql")
    _write(root, "services/shop/dblift-shop.yml", CONFIG)
    _write(root, "services/shop/migrations/V1__a.sql")

    assert _kinds(discover(str(root))) == [
        ("services/billing/dblift.yaml", "named"),
        ("services/shop/dblift-shop.yml", "named"),
    ]


def test_custom_named_config_is_found_by_its_content(tmp_path):
    root = tmp_path / "shop"
    _write(root, "config/database.yaml", CONFIG)
    _write(root, "config/app.yaml", "server:\n  port: 8080\n")
    _write(root, "docker-compose.yml", "services:\n  db:\n    image: postgres\n")
    _write(root, "only-database.yaml", "database:\n  type: sqlite\n  path: x\n")

    assert _kinds(discover(str(root))) == [("config/database.yaml", "content")]


def test_templates_and_examples_are_listed_apart(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", CONFIG)
    _write(root, "dblift.yaml.template", CONFIG)
    _write(root, "docs/examples/dblift.yaml", CONFIG)
    _write(root, "examples/other.yaml", CONFIG)

    assert _kinds(discover(str(root))) == [
        ("dblift.yaml", "named"),
        ("dblift.yaml.template", "template"),
        ("docs/examples/dblift.yaml", "template"),
    ]


def test_a_broken_config_is_reported_with_its_problem_and_no_file_text(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", "database:\n  type: postgresql\n  password: s3cret-value: oops\n")
    _write(root, "dblift-list.yaml", "- a\n- b\n")
    _write(root, "dblift-empty.yaml", "migrations:\n  directory: ./m\n")

    by_path = {c.path: c for c in discover(str(root)).configs}

    assert "line" in by_path["dblift.yaml"].problem
    assert "s3cret-value" not in by_path["dblift.yaml"].problem
    assert by_path["dblift-list.yaml"].problem == "not a mapping"
    assert by_path["dblift-empty.yaml"].problem == "no database section"


def test_flyway_projects_are_noticed(tmp_path):
    root = tmp_path / "legacy"
    _write(root, "flyway.conf", "flyway.url=jdbc:postgresql://db/shop\n")
    _write(root, "db/flyway.toml", "[flyway]\n")

    found = discover(str(root))

    assert found.flyway == ["db/flyway.toml", "flyway.conf"]
    assert found.configs == []


def test_script_folders_without_a_config_are_listed(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", CONFIG)
    _write(root, "migrations/V1_0_0__a.sql")
    _write(root, "migrations/nested/V1_0_1__b.sql")
    _write(root, "legacy/sql/V1__old.sql")
    _write(root, "legacy/sql/U1__old.sql")
    _write(root, "notes/README.sql")

    assert discover(str(root)).script_folders == ["legacy/sql"]


def test_a_template_does_not_claim_a_script_folder(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml.template", CONFIG)
    _write(root, "migrations/V1_0_0__a.sql")

    assert discover(str(root)).script_folders == ["migrations"]


def test_registered_configs_are_marked(tmp_path):
    root = tmp_path / "shop"
    config = _write(root, "dblift.yaml", CONFIG)
    _write(root, "other/dblift.yaml", CONFIG)

    found = discover(str(root), registered=[str(config.resolve())])

    assert [(c.path, c.registered) for c in found.configs] == [
        ("dblift.yaml", True),
        ("other/dblift.yaml", False),
    ]


def test_dependency_and_tooling_folders_are_skipped(tmp_path):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", CONFIG)
    for folder in ("node_modules/pkg", ".venv/lib", "__pycache__", ".git/hooks", "venv/x"):
        _write(root, f"{folder}/dblift.yaml", CONFIG)

    assert _kinds(discover(str(root))) == [("dblift.yaml", "named")]


def test_in_a_git_repository_ignored_files_are_left_out_and_the_branch_is_reported(tmp_path):
    root = _repo(tmp_path / "shop")
    _write(root, ".gitignore", "local/\n*.secret.yaml\n")
    _write(root, "dblift.yaml", CONFIG)
    _write(root, "untracked/dblift.yaml", CONFIG)
    _write(root, "local/dblift.yaml", CONFIG)
    _write(root, "dblift.secret.yaml", CONFIG)
    _git(root, "add", "dblift.yaml", ".gitignore")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "switch", "-q", "-c", "feature/x")

    found = discover(str(root))

    assert found.repository is True and found.branch == "feature/x"
    assert _kinds(found) == [("dblift.yaml", "named"), ("untracked/dblift.yaml", "named")]


def test_links_out_of_the_folder_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    _write(outside, "dblift.yaml", CONFIG)
    _write(outside, "secret.yaml", CONFIG)
    root = tmp_path / "shop"
    root.mkdir()
    os.symlink(outside, root / "linked")
    os.symlink(outside / "secret.yaml", root / "dblift.yaml")

    found = discover(str(root))

    assert found.configs == []


def test_a_very_large_tree_is_cut_short_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_FILES", 5)
    root = tmp_path / "big"
    for index in range(12):
        _write(root, f"data/file{index}.txt")

    assert discover(str(root)).truncated is True


def test_a_huge_yaml_file_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "MAX_YAML_BYTES", 50)
    root = tmp_path / "shop"
    _write(root, "config/database.yaml", CONFIG + "# " + "x" * 200 + "\n")
    _write(root, "dblift.yaml", CONFIG + "# " + "x" * 200 + "\n")

    by_path = {c.path: c for c in discover(str(root)).configs}

    assert "config/database.yaml" not in by_path
    assert by_path["dblift.yaml"].problem == "too large to inspect"


@pytest.mark.parametrize("folder", ["", "   ", "relative/path", "/definitely/not/here"])
def test_refuses_what_is_not_an_existing_absolute_folder(folder):
    with pytest.raises(DiscoveryError):
        discover(folder)


def test_refuses_a_file(tmp_path):
    with pytest.raises(DiscoveryError):
        discover(str(_write(tmp_path, "dblift.yaml", CONFIG)))


def test_reads_nothing_but_names_and_yaml(tmp_path, monkeypatch):
    root = tmp_path / "shop"
    _write(root, "dblift.yaml", CONFIG)
    _write(root, "dev.db", "not yaml")
    _write(root, "migrations/V1__a.sql", "CREATE TABLE a (id INTEGER);")
    opened = []
    real_open = open

    def spy(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)
    discover(str(root))

    assert all(name.endswith((".yaml", ".yml")) for name in opened), opened
