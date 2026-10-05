import os
import stat
import threading

import pytest
import yaml
from dblift_ui import configs
from dblift_ui.configs import (
    ConfigError,
    ConfigForm,
    Connection,
    EnvironmentForm,
    Password,
    StaleConfig,
    check,
    create_file,
    render,
    revision,
    update_file,
)


def _pg(**connection):
    defaults = dict(host="db.example.com", port=5432, database="shop", username="app")
    defaults.update(connection)
    return ConfigForm(engine="postgresql", connection=Connection(**defaults))


def _sqlite():
    return ConfigForm(
        engine="sqlite", connection=Connection(path="./dev.db", password=Password(mode="none"))
    )


def test_a_good_config_has_no_problem(monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")

    assert check(render(_pg()), []) == configs.Check(problems=[], warnings=[])


def test_sqlite_is_valid_without_a_password():
    assert check(render(_sqlite()), []).problems == []


def test_an_unset_variable_is_a_warning_not_a_problem(monkeypatch):
    monkeypatch.delenv("DBLIFT_DB_PASSWORD", raising=False)

    result = check(render(_pg()), [])

    assert result.problems == []
    assert len(result.warnings) == 1 and "DBLIFT_DB_PASSWORD" in result.warnings[0]


def test_the_loader_reports_a_missing_password():
    result = check(render(_pg(password=Password(mode="none"))), [])

    assert len(result.problems) == 1 and "password" in result.problems[0].lower()


def test_each_environment_is_checked(monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    text = render(_pg()) + "environments:\n  broken:\n    database:\n      url: nope://x/y\n"

    result = check(text, ["broken"])

    assert len(result.problems) == 1 and result.problems[0].startswith("broken: ")


def test_a_missing_driver_is_a_warning(monkeypatch):
    def missing(*args, **kwargs):
        raise ModuleNotFoundError("No module named 'ibm_db_sa'", name="ibm_db_sa")

    monkeypatch.setattr(configs.DBLiftClient, "from_config_file", missing)

    result = check(render(_sqlite()), [])

    assert result.problems == []
    assert "ibm_db_sa" in result.warnings[0] and "not installed" in result.warnings[0]


def test_problems_carry_no_password_and_no_temporary_path(monkeypatch):
    seen = {}

    def explode(path, *args, **kwargs):
        seen["path"] = path
        raise RuntimeError(f"cannot use postgresql://app:hunter2@h/db from {path}")

    monkeypatch.setattr(configs.DBLiftClient, "from_config_file", explode)

    problem = check(render(_sqlite()), []).problems[0]

    assert "hunter2" not in problem
    assert os.path.dirname(seen["path"]) not in problem
    assert not os.path.exists(seen["path"])


def test_checking_writes_nothing_where_it_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")

    check(render(_pg()), [])

    assert list(tmp_path.iterdir()) == []


def test_checking_writes_no_log_where_the_config_points(tmp_path):
    logs = tmp_path / "project"
    logs.mkdir()
    text = render(_sqlite()) + f"log_file: {logs}/flat.log\nlogging:\n  file: {logs}/nested.log\n"

    assert check(text, []).problems == []
    assert list(logs.iterdir()) == []


def test_a_config_with_a_secrets_section_is_not_loaded(monkeypatch):
    monkeypatch.setattr(
        configs.DBLiftClient,
        "from_config_file",
        lambda *a, **k: pytest.fail("the loader must not run"),
    )

    result = check(render(_sqlite()) + "secrets:\n  provider: vault\n", [])

    assert result.problems == [] and "secrets" in result.warnings[0]


def test_create_writes_the_file_and_the_migrations_folder(tmp_path):
    path = create_file(str(tmp_path), "dblift.yaml", _sqlite())

    assert path == tmp_path.resolve() / "dblift.yaml"
    assert yaml.safe_load(path.read_text())["database"] == {"type": "sqlite", "path": "./dev.db"}
    assert (tmp_path / "migrations").is_dir()


def test_create_never_overwrites(tmp_path):
    (tmp_path / "dblift.yaml").write_text("keep me\n")

    with pytest.raises(ConfigError, match="already exists"):
        create_file(str(tmp_path), "dblift.yaml", _sqlite())

    assert (tmp_path / "dblift.yaml").read_text() == "keep me\n"


@pytest.mark.parametrize(
    "name", ["config.yaml", "../dblift.yaml", "dblift.yaml/x", "dblift.txt", "", "dblift.yaml\n"]
)
def test_create_refuses_other_file_names(tmp_path, name):
    with pytest.raises(ConfigError, match="file name"):
        create_file(str(tmp_path), name, _sqlite())


@pytest.mark.parametrize("folder", ["", "relative", "/definitely/not/here"])
def test_create_refuses_a_bad_folder(folder):
    with pytest.raises(ConfigError, match="folder"):
        create_file(folder, "dblift.yaml", _sqlite())


def test_create_does_not_follow_a_link(tmp_path):
    target = tmp_path / "elsewhere.txt"
    os.symlink(target, tmp_path / "dblift.yaml")

    with pytest.raises(ConfigError):
        create_file(str(tmp_path), "dblift.yaml", _sqlite())

    assert not target.exists()


def test_create_refuses_a_config_the_loader_rejects(tmp_path):
    with pytest.raises(ConfigError, match="password"):
        create_file(str(tmp_path), "dblift.yaml", _pg(password=Password(mode="none")))

    assert list(tmp_path.iterdir()) == []


def test_a_migrations_folder_outside_the_project_is_not_created(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    form = _sqlite()
    form.migrations_directory = "../outside"

    create_file(str(project), "dblift.yaml", form)

    assert not (tmp_path / "outside").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_file_with_a_literal_password_is_private(tmp_path):
    create_file(
        str(tmp_path), "dblift.yaml", _pg(password=Password(mode="literal", value="s3cret"))
    )

    assert stat.S_IMODE((tmp_path / "dblift.yaml").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_a_file_with_a_password_in_its_url_is_private(tmp_path):
    form = _pg(
        mode="url", url="postgresql://app:s3cret@h:5432/shop", password=Password(mode="none")
    )

    create_file(str(tmp_path), "dblift.yaml", form)

    assert stat.S_IMODE((tmp_path / "dblift.yaml").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_an_update_keeping_a_literal_password_makes_the_file_private(tmp_path):
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg(password=Password(mode="literal", value="s3cret"))))
    os.chmod(path, 0o644)

    update_file(
        str(path), _pg(host="other", password=Password(mode="keep")), revision(path.read_text())
    )

    assert "s3cret" in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_an_update_without_a_stored_password_keeps_the_files_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg()))
    os.chmod(path, 0o640)

    update_file(str(path), _pg(host="other"), revision(path.read_text()))

    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_update_rewrites_in_place_keeping_comments(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text("# mine\n" + render(_pg()))
    form = _pg(host="other.example.com")

    update_file(str(path), form, revision(path.read_text()))

    text = path.read_text()
    assert text.startswith("# mine\n") and "other.example.com" in text
    assert [p.name for p in tmp_path.iterdir()] == ["dblift.yaml"]


def test_update_refuses_a_file_that_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg()))
    stale = revision(path.read_text())
    path.write_text(render(_pg()) + "# edited by hand\n")

    with pytest.raises(StaleConfig):
        update_file(str(path), _pg(host="other"), stale)

    assert "edited by hand" in path.read_text()


def test_of_two_saves_from_the_same_revision_only_the_first_lands(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg()))
    read = revision(path.read_text())
    real_check, second = configs.check, []

    def check_while_another_save_starts(text, environments):
        if not second:  # the first save, mid-check: a second one arrives
            thread = threading.Thread(target=lambda: second.append(_save(path, "second", read)))
            second.append(thread)
            thread.start()
            thread.join(timeout=0.5)
        return real_check(text, environments)

    monkeypatch.setattr(configs, "check", check_while_another_save_starts)

    update_file(str(path), _pg(host="first"), read)
    second[0].join(timeout=10)

    assert isinstance(second[1], StaleConfig)
    assert "first" in path.read_text()


def test_an_edit_made_while_checking_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg()))
    read = revision(path.read_text())
    real_check = configs.check

    def check_while_edited(text, environments):
        path.write_text(path.read_text() + "# edited by hand\n")
        return real_check(text, environments)

    monkeypatch.setattr(configs, "check", check_while_edited)

    with pytest.raises(StaleConfig):
        update_file(str(path), _pg(host="other"), read)

    assert "edited by hand" in path.read_text()


def _save(path, host, read):
    try:
        update_file(str(path), _pg(host=host), read)
    except ConfigError as exc:
        return exc
    return None


def test_update_refuses_a_config_the_loader_rejects(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "x")
    path = tmp_path / "dblift.yaml"
    path.write_text(render(_pg()))
    before = path.read_text()
    form = _pg()
    form.environments = [
        EnvironmentForm(
            name="bad",
            connection=Connection(mode="url", url="nope://x/y", password=Password(mode="none")),
        )
    ]

    with pytest.raises(ConfigError, match="bad"):
        update_file(str(path), form, revision(before))

    assert path.read_text() == before
