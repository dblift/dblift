import ast
import os

import pytest
import yaml
from dblift_ui.scripts import (
    MAX_BYTES,
    ScriptError,
    ScriptNotFound,
    ScriptStore,
    yaml_problem,
)


def _names(store):
    return [s.name for s in store.list()]


def test_lists_versioned_scripts_in_version_order_with_their_undo(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    (migrations / "V1_0_10__later.sql").write_text("SELECT 1;\n")
    (migrations / "V1_0_2__third.py").write_text("def migrate(context):\n    pass\n")
    (migrations / "R__refresh_view.sql").write_text("SELECT 1;\n")

    listed = ScriptStore(str(sqlite_project)).list()

    assert [s.name for s in listed] == [
        "V1_0_0__create_customers.sql",
        "V1_0_1__create_orders.sql",
        "V1_0_2__third.py",
        "V1_0_10__later.sql",
        "R__refresh_view.sql",
    ]
    first, third, last = listed[0], listed[2], listed[4]
    assert (first.kind, first.version, first.language, first.has_undo) == (
        "versioned",
        "1.0.0",
        "sql",
        True,
    )
    assert first.description == "create_customers"
    assert first.directory == "migrations"
    assert (third.language, third.has_undo) == ("python", False)
    assert (last.kind, last.version) == ("repeatable", "")


def test_finds_scripts_in_sub_folders_and_reports_where(sqlite_project):
    nested = sqlite_project.parent / "migrations" / "billing"
    nested.mkdir()
    (nested / "V1_0_2__invoices.sql").write_text("SELECT 1;\n")

    script = ScriptStore(str(sqlite_project)).list()[-1]

    assert (script.name, script.directory) == ("V1_0_2__invoices.sql", "migrations/billing")


def test_respects_a_non_recursive_directory(sqlite_project):
    nested = sqlite_project.parent / "migrations" / "billing"
    nested.mkdir()
    (nested / "V1_0_2__invoices.sql").write_text("SELECT 1;\n")
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n"
        "migrations:\n  directories:\n    - path: ./migrations\n      recursive: false\n"
    )

    assert "V1_0_2__invoices.sql" not in _names(ScriptStore(str(sqlite_project)))


def test_reads_several_directories(sqlite_project):
    extra = sqlite_project.parent / "more"
    extra.mkdir()
    (extra / "V2_0_0__extra.sql").write_text("SELECT 2;\n")
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n"
        "migrations:\n  directories:\n    - ./migrations\n    - ./more\n"
    )

    store = ScriptStore(str(sqlite_project))

    assert _names(store)[-1] == "V2_0_0__extra.sql"
    assert store.read("V2_0_0__extra.sql") == "SELECT 2;\n"


def test_ignores_files_that_are_not_scripts(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    (migrations / "README.md").write_text("notes")
    (migrations / "V1__no_double_underscore.txt").write_text("x")
    (migrations / "__pycache__").mkdir()
    (migrations / "__pycache__" / "V9_9_9__cached.py").write_text("x")

    assert _names(ScriptStore(str(sqlite_project))) == [
        "V1_0_0__create_customers.sql",
        "V1_0_1__create_orders.sql",
    ]


def test_reads_and_writes_a_script_and_its_undo(sqlite_project):
    store = ScriptStore(str(sqlite_project))

    assert (
        store.read("V1_0_0__create_customers.sql")
        == "CREATE TABLE customers (id INTEGER PRIMARY KEY);\n"
    )
    store.write("U1_0_0__create_customers.sql", "DROP TABLE IF EXISTS customers;\n")

    assert store.read("U1_0_0__create_customers.sql") == "DROP TABLE IF EXISTS customers;\n"
    leftovers = [
        p.name for p in (sqlite_project.parent / "migrations").iterdir() if p.name.endswith(".tmp")
    ]
    assert leftovers == []


@pytest.mark.parametrize(
    "name",
    [
        "../dblift.yaml",
        "..%2Fdblift.yaml",
        "/etc/passwd",
        "migrations/V1_0_0__create_customers.sql",
        "dblift.yaml",
        "dev.db",
        "V1_0_0__create_customers.sql/..",
        "V1_0_0__create customers.sql",
        "V1_0_0__create_customers.sh",
        "X1_0_0__create_customers.sql",
        "",
    ],
)
def test_refuses_names_that_are_not_plain_script_names(sqlite_project, name):
    store = ScriptStore(str(sqlite_project))
    with pytest.raises(ScriptError):
        store.read(name)
    with pytest.raises(ScriptError):
        store.write(name, "x")


def test_unknown_script_is_not_found(sqlite_project):
    store = ScriptStore(str(sqlite_project))
    with pytest.raises(ScriptNotFound):
        store.read("V9_9_9__nothing.sql")
    with pytest.raises(ScriptNotFound):
        store.write("V9_9_9__nothing.sql", "SELECT 1;\n")
    assert not (sqlite_project.parent / "migrations" / "V9_9_9__nothing.sql").exists()


def test_a_symlink_pointing_outside_is_not_served(sqlite_project, tmp_path):
    secret = tmp_path / "secret.sql"
    secret.write_text("TOP SECRET\n")
    link = sqlite_project.parent / "migrations" / "V1_0_2__linked.sql"
    os.symlink(secret, link)

    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__linked.sql" not in _names(store)
    with pytest.raises(ScriptError):
        store.read("V1_0_2__linked.sql")
    with pytest.raises(ScriptError):
        store.write("V1_0_2__linked.sql", "overwritten\n")
    assert secret.read_text() == "TOP SECRET\n"


def test_size_cap_on_read_and_write(sqlite_project):
    store = ScriptStore(str(sqlite_project))
    big = sqlite_project.parent / "migrations" / "V1_0_2__big.sql"
    big.write_text("-" * (MAX_BYTES + 1))

    with pytest.raises(ScriptError, match="too large"):
        store.read("V1_0_2__big.sql")
    with pytest.raises(ScriptError, match="too large"):
        store.write("V1_0_0__create_customers.sql", "-" * (MAX_BYTES + 1))


def test_a_file_that_is_not_text_is_refused(sqlite_project):
    (sqlite_project.parent / "migrations" / "V1_0_2__binary.sql").write_bytes(b"\xff\xfe\x00\x01")

    with pytest.raises(ScriptError, match="UTF-8"):
        ScriptStore(str(sqlite_project)).read("V1_0_2__binary.sql")


def test_two_files_with_the_same_name_are_reported(sqlite_project):
    nested = sqlite_project.parent / "migrations" / "copy"
    nested.mkdir()
    (nested / "V1_0_0__create_customers.sql").write_text("SELECT 1;\n")

    with pytest.raises(ScriptError, match="two files"):
        ScriptStore(str(sqlite_project)).read("V1_0_0__create_customers.sql")


def test_undo_paths_name_each_undo_file_by_its_migration(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    (migrations / "undo").mkdir()
    (migrations / "U1_0_1__create_orders.sql").rename(
        migrations / "undo" / "U1_0_1__create_orders.sql"
    )
    (migrations / "other").mkdir()
    (migrations / "other" / "U1_0_0__create_customers.sql").write_text("SELECT 0;\n")

    paths = ScriptStore(str(sqlite_project)).undo_paths()

    # Two files share the first undo name: which one counts is unknown, so neither is given.
    assert paths == {
        "V1_0_1__create_orders.sql": (migrations / "undo" / "U1_0_1__create_orders.sql").resolve()
    }


def test_create_versioned_sql_takes_the_next_version_and_adds_an_undo(sqlite_project):
    store = ScriptStore(str(sqlite_project))

    created = store.create("versioned", "sql", "Add invoices table!")

    assert created == ["V1_0_2__add_invoices_table.sql", "U1_0_2__add_invoices_table.sql"]
    assert store.read(created[0]) == "-- Add invoices table!\n"
    assert store.read(created[1]) == "-- Undo: Add invoices table!\n"
    assert store.list()[-1].has_undo is True


def test_create_keeps_the_number_of_version_parts(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    for path in migrations.iterdir():
        path.unlink()
    (migrations / "V7__only.sql").write_text("SELECT 1;\n")

    assert ScriptStore(str(sqlite_project)).create("versioned", "sql", "next")[0] == "V8__next.sql"


def test_create_starts_at_1_0_0_in_an_empty_project(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    for path in migrations.iterdir():
        path.unlink()
    migrations.rmdir()

    created = ScriptStore(str(sqlite_project)).create("versioned", "sql", "first")

    assert created[0] == "V1_0_0__first.sql"
    assert (migrations / "V1_0_0__first.sql").is_file()


def test_create_python_scripts_that_compile(sqlite_project):
    store = ScriptStore(str(sqlite_project))

    created = store.create("versioned", "python", "seed data")

    assert created == ["V1_0_2__seed_data.py", "U1_0_2__seed_data.py"]
    for name in created:
        source = store.read(name)
        compile(source, name, "exec")
        assert "def migrate(context" in source
        assert "from dblift.api import MigrationContext" in source


def test_create_repeatable(sqlite_project):
    store = ScriptStore(str(sqlite_project))

    assert store.create("repeatable", "sql", "refresh customer view") == [
        "R__refresh_customer_view.sql"
    ]
    assert store.list()[-1].kind == "repeatable"


def test_create_never_overwrites(sqlite_project):
    store = ScriptStore(str(sqlite_project))
    store.create("repeatable", "sql", "refresh view")

    with pytest.raises(ScriptError, match="already exists"):
        store.create("repeatable", "sql", "refresh view")


@pytest.mark.parametrize(
    "kind,language,description",
    [
        ("versioned", "sql", "   "),
        ("versioned", "sql", "!!!"),
        ("nope", "sql", "x"),
        ("versioned", "ruby", "x"),
        ("undo", "sql", "x"),
    ],
)
def test_create_refuses_bad_requests(sqlite_project, kind, language, description):
    with pytest.raises(ScriptError):
        ScriptStore(str(sqlite_project)).create(kind, language, description)


def test_a_broken_config_is_reported(sqlite_project):
    sqlite_project.write_text("migrations: [unclosed")
    with pytest.raises(ScriptError, match="config"):
        ScriptStore(str(sqlite_project))


# Beyond the brief: confinement cases that must reach the store's own checks.


def test_a_symlinked_sub_folder_pointing_outside_is_not_served(sqlite_project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "V1_0_2__outside.sql").write_text("TOP SECRET\n")
    os.symlink(outside, sqlite_project.parent / "migrations" / "linked")

    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__outside.sql" not in _names(store)
    with pytest.raises(ScriptError):
        store.read("V1_0_2__outside.sql")
    with pytest.raises(ScriptError):
        store.write("V1_0_2__outside.sql", "overwritten\n")
    assert (outside / "V1_0_2__outside.sql").read_text() == "TOP SECRET\n"


def test_a_symlink_to_the_config_inside_the_migrations_folder_is_not_served(sqlite_project):
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: .\n"
    )
    before = sqlite_project.read_text()
    os.symlink(sqlite_project, sqlite_project.parent / "V1_0_2__config.sql")

    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__config.sql" not in _names(store)
    with pytest.raises(ScriptError):
        store.read("V1_0_2__config.sql")
    with pytest.raises(ScriptError):
        store.write("V1_0_2__config.sql", "x")
    assert sqlite_project.read_text() == before


def test_a_link_to_a_script_named_file_outside_is_not_served(sqlite_project, tmp_path):
    secret = tmp_path / "V9_0_0__secret.sql"
    secret.write_text("TOP SECRET\n")
    os.symlink(secret, sqlite_project.parent / "migrations" / "V1_0_2__linked.sql")
    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__linked.sql" not in _names(store)
    with pytest.raises(ScriptError):
        store.read("V1_0_2__linked.sql")
    with pytest.raises(ScriptError):
        store.write("V1_0_2__linked.sql", "overwritten\n")
    assert secret.read_text() == "TOP SECRET\n"


def test_a_pipe_named_like_a_script_is_never_opened(sqlite_project):
    os.mkfifo(sqlite_project.parent / "migrations" / "V1_0_2__pipe.sql")
    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__pipe.sql" not in _names(store)
    with pytest.raises(ScriptNotFound):
        store.read("V1_0_2__pipe.sql")


@pytest.mark.parametrize("recursive", ["true", "false"])
def test_a_folder_named_like_a_script_is_not_a_script(sqlite_project, recursive):
    (sqlite_project.parent / "migrations" / "V1_0_2__folder.sql").mkdir()
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n"
        f"migrations:\n  directories:\n    - path: ./migrations\n      recursive: {recursive}\n"
    )
    store = ScriptStore(str(sqlite_project))

    assert "V1_0_2__folder.sql" not in _names(store)
    with pytest.raises(ScriptNotFound):
        store.read("V1_0_2__folder.sql")
    with pytest.raises(ScriptNotFound):
        store.write("V1_0_2__folder.sql", "x")
    assert (sqlite_project.parent / "migrations" / "V1_0_2__folder.sql").is_dir()


@pytest.mark.parametrize("name", ["..", ".", "V1_0_0__create_customers.sql\n"])
def test_refuses_dot_names_and_a_trailing_newline(sqlite_project, name):
    store = ScriptStore(str(sqlite_project))
    with pytest.raises(ScriptError) as read:
        store.read(name)
    with pytest.raises(ScriptError) as write:
        store.write(name, "x")
    assert not isinstance(read.value, ScriptNotFound)
    assert not isinstance(write.value, ScriptNotFound)


def test_saving_never_writes_through_a_symlinked_temporary_file(sqlite_project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched\n")
    migrations = sqlite_project.parent / "migrations"
    os.symlink(outside, migrations / "V1_0_0__create_customers.sql.tmp")
    store = ScriptStore(str(sqlite_project))

    store.write("V1_0_0__create_customers.sql", "SELECT 2;\n")

    assert outside.read_text() == "untouched\n"
    assert store.read("V1_0_0__create_customers.sql") == "SELECT 2;\n"
    assert (migrations / "V1_0_0__create_customers.sql").is_file()
    assert not (migrations / "V1_0_0__create_customers.sql").is_symlink()
    assert (migrations / "V1_0_0__create_customers.sql.tmp").is_symlink()


def test_saving_replaces_the_target_of_an_inside_link_not_the_link(sqlite_project):
    migrations = sqlite_project.parent / "migrations"
    shared = migrations / "shared"
    shared.mkdir()
    (shared / "R__view.sql").write_text("SELECT 1;\n")
    os.symlink(shared / "R__view.sql", migrations / "R__alias.sql")
    store = ScriptStore(str(sqlite_project))

    store.write("R__alias.sql", "SELECT 2;\n")

    assert (migrations / "R__alias.sql").is_symlink()
    assert (shared / "R__view.sql").read_text() == "SELECT 2;\n"


def test_a_failed_save_keeps_the_script_and_leaves_no_temporary_file(sqlite_project, monkeypatch):
    migrations = sqlite_project.parent / "migrations"
    before = sorted(p.name for p in migrations.iterdir())
    store = ScriptStore(str(sqlite_project))

    def disk_full(source, target):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("dblift_ui.scripts.os.replace", disk_full)
    with pytest.raises(ScriptError, match="No space left"):
        store.write("V1_0_0__create_customers.sql", "SELECT 2;\n")
    monkeypatch.undo()

    assert sorted(p.name for p in migrations.iterdir()) == before
    assert (
        store.read("V1_0_0__create_customers.sql")
        == "CREATE TABLE customers (id INTEGER PRIMARY KEY);\n"
    )


def test_saving_keeps_the_file_permissions(sqlite_project):
    script = sqlite_project.parent / "migrations" / "V1_0_0__create_customers.sql"
    script.chmod(0o644)

    ScriptStore(str(sqlite_project)).write("V1_0_0__create_customers.sql", "SELECT 2;\n")

    assert script.stat().st_mode & 0o777 == 0o644


def test_text_that_cannot_be_encoded_is_refused(sqlite_project):
    with pytest.raises(ScriptError, match="UTF-8"):
        ScriptStore(str(sqlite_project)).write("V1_0_0__create_customers.sql", "bad \ud800\n")


def test_create_never_writes_through_a_dangling_symlink(sqlite_project, tmp_path):
    target = tmp_path / "planted.sql"
    os.symlink(target, sqlite_project.parent / "migrations" / "R__refresh_view.sql")

    with pytest.raises(ScriptError, match="already exists"):
        ScriptStore(str(sqlite_project)).create("repeatable", "sql", "refresh view")

    assert not target.exists()


def test_a_description_with_quotes_and_backslashes_stays_in_the_docstring(sqlite_project):
    store = ScriptStore(str(sqlite_project))
    description = 'Drop """evil""" table \\ now\\x00\x00 \\'

    created = store.create("versioned", "python", description)
    plain = store.create("repeatable", "python", "plain")

    reference = ast.parse(store.read(plain[0]))
    for name in created:
        source = store.read(name)
        compile(source, name, "exec")
        module = ast.parse(source)
        docstring = module.body[0]
        assert isinstance(docstring, ast.Expr)
        assert "evil" in ast.literal_eval(docstring.value)
        assert ast.dump(ast.Module(body=module.body[1:], type_ignores=[])) == ast.dump(
            ast.Module(body=reference.body[1:], type_ignores=[])
        )
        outside = source.replace(ast.get_source_segment(source, docstring), "")
        for word in ("Drop", "evil", "table", "now"):
            assert word not in outside


def test_a_description_cannot_break_out_of_the_sql_comment(sqlite_project):
    store = ScriptStore(str(sqlite_project))

    created = store.create("repeatable", "sql", "view\nDROP TABLE customers;\r --")

    assert store.read(created[0]) == "-- view DROP TABLE customers; --\n"


# Review fixes: a bounded walk, safe config errors, platforms without O_NOFOLLOW/fchmod.

TOO_MANY = "the migrations directory holds too many files to list here"


def test_a_huge_migrations_directory_is_refused_before_anything_is_written(
    sqlite_project, monkeypatch
):
    monkeypatch.setattr("dblift_ui.scripts.MAX_ENTRIES", 3)
    migrations = sqlite_project.parent / "migrations"
    before = {p.name: p.read_text() for p in migrations.iterdir()}
    store = ScriptStore(str(sqlite_project))

    for attempt in (
        store.list,
        lambda: store.read("V1_0_0__create_customers.sql"),
        lambda: store.write("V1_0_0__create_customers.sql", "SELECT 2;\n"),
        lambda: store.create("versioned", "sql", "more"),
    ):
        with pytest.raises(ScriptError, match=TOO_MANY):
            attempt()

    assert {p.name: p.read_text() for p in migrations.iterdir()} == before


def test_the_walk_limit_counts_every_directory_together(sqlite_project, monkeypatch):
    extra = sqlite_project.parent / "more"
    extra.mkdir()
    (extra / "V2_0_0__extra.sql").write_text("SELECT 2;\n")
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n"
        "migrations:\n  directories:\n    - ./migrations\n    - ./more\n"
    )
    monkeypatch.setattr("dblift_ui.scripts.MAX_ENTRIES", 4)

    with pytest.raises(ScriptError, match=TOO_MANY):
        ScriptStore(str(sqlite_project)).list()


def test_a_config_error_never_quotes_the_config(sqlite_project):
    sqlite_project.write_text(
        "database:\n  type: sqlite\n  path: ./dev.db\n  password: s3cret-value: oops\n"
    )

    with pytest.raises(ScriptError) as error:
        ScriptStore(str(sqlite_project))

    assert "line 4" in str(error.value)
    assert "s3cret-value" not in str(error.value)


def test_yaml_problem_falls_back_without_details():
    assert yaml_problem(yaml.YAMLError("raw text s3cret")) == "the file is not valid YAML"


def test_works_without_o_nofollow_and_fchmod(sqlite_project, monkeypatch):
    script = sqlite_project.parent / "migrations" / "V1_0_0__create_customers.sql"
    script.chmod(0o644)
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    monkeypatch.delattr(os, "fchmod", raising=False)
    store = ScriptStore(str(sqlite_project))

    store.write("V1_0_0__create_customers.sql", "SELECT 2;\n")

    assert store.read("V1_0_0__create_customers.sql") == "SELECT 2;\n"
    assert script.stat().st_mode & 0o777 == 0o644


def test_a_mode_that_cannot_be_set_does_not_fail_the_save(sqlite_project, monkeypatch):
    def refused(*args, **kwargs):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("dblift_ui.scripts.os.chmod", refused)
    store = ScriptStore(str(sqlite_project))

    store.write("V1_0_0__create_customers.sql", "SELECT 2;\n")
    monkeypatch.undo()

    assert store.read("V1_0_0__create_customers.sql") == "SELECT 2;\n"
