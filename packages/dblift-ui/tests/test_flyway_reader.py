import os
import time

import pytest
from dblift_ui import flyway
from dblift_ui.flyway import DEFAULT_TABLE, FlywayError, read_project, table_beside


def _project(tmp_path, text, name="flyway.conf", folders=("sql",)):
    root = tmp_path / "legacy"
    root.mkdir()
    for folder in folders:
        (root / folder).mkdir(parents=True)
    (root / name).write_text(text)
    return root


CONF = """\
# Flyway settings
flyway.url=jdbc:postgresql://db.example.com:5432/shop
flyway.user = app
flyway.password=hunter2
flyway.schemas=sales,audit
flyway.locations=filesystem:sql
flyway.table=schema_version
"""


def test_reads_a_conf_file_into_a_form(tmp_path):
    root = _project(tmp_path, CONF)

    found = read_project(str(root), "flyway.conf")

    assert found.folder == str(root.resolve())
    assert found.table == "schema_version"
    form = found.form
    assert form.engine == "postgresql"
    connection = form.connection
    assert (connection.host, connection.port, connection.database) == (
        "db.example.com",
        5432,
        "shop",
    )
    assert (connection.username, connection.schema_) == ("app", "sales")
    assert form.migrations_directory == "./sql"


def test_the_flyway_password_never_leaves(tmp_path):
    root = _project(tmp_path, CONF)

    found = read_project(str(root), "flyway.conf")

    assert found.form.connection.password.mode == "env"
    assert found.form.connection.password.value == "DBLIFT_DB_PASSWORD"
    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)
    assert any("password" in note and "not copied" in note for note in found.notes)


@pytest.mark.parametrize(
    "url, engine, expected",
    [
        (
            "jdbc:postgresql://h:5433/shop?ssl=true",
            "postgresql",
            dict(host="h", port=5433, database="shop"),
        ),
        ("jdbc:postgresql://h/shop", "postgresql", dict(host="h", port=None, database="shop")),
        ("jdbc:mysql://h:3306/shop", "mysql", dict(host="h", port=3306, database="shop")),
        ("jdbc:mariadb://h:3307/shop", "mariadb", dict(host="h", port=3307, database="shop")),
        ("jdbc:redshift://h:5439/dw", "redshift", dict(host="h", port=5439, database="dw")),
        ("jdbc:db2://h:50000/SHOP", "db2", dict(host="h", port=50000, database="SHOP")),
        ("jdbc:mongodb://h:27017/shop", "mongodb", dict(host="h", port=27017, database="shop")),
        (
            "jdbc:sqlserver://h:1433;databaseName=shop;encrypt=true",
            "sqlserver",
            dict(host="h", port=1433, database="shop"),
        ),
        (
            "jdbc:sqlserver://h;database=shop",
            "sqlserver",
            dict(host="h", port=None, database="shop"),
        ),
        (
            "jdbc:oracle:thin:@//h:1521/FREEPDB1",
            "oracle",
            dict(host="h", port=1521, service_name="FREEPDB1"),
        ),
        (
            "jdbc:oracle:thin:@h:1521/FREEPDB1",
            "oracle",
            dict(host="h", port=1521, service_name="FREEPDB1"),
        ),
        ("jdbc:oracle:thin:@h:1521:XE", "oracle", dict(host="h", port=1521, service_name="XE")),
        ("jdbc:sqlite:legacy.db", "sqlite", dict(path="./legacy.db")),
        ("jdbc:sqlite:/var/data/legacy.db", "sqlite", dict(path="/var/data/legacy.db")),
        (
            "jdbc:snowflake://acme-xy1.snowflakecomputing.com/?db=SHOP&warehouse=WH",
            "snowflake",
            dict(account="acme-xy1", database="SHOP", warehouse="WH"),
        ),
    ],
)
def test_jdbc_urls_are_translated(tmp_path, url, engine, expected):
    root = _project(tmp_path, f"flyway.url={url}\nflyway.locations=filesystem:sql\n")

    form = read_project(str(root), "flyway.conf").form

    assert form.engine == engine
    assert {key: getattr(form.connection, key) for key in expected} == expected


def test_an_oracle_sid_is_flagged(tmp_path):
    root = _project(tmp_path, "flyway.url=jdbc:oracle:thin:@h:1521:XE\n")

    assert any("SID" in note for note in read_project(str(root), "flyway.conf").notes)


@pytest.mark.parametrize(
    "url",
    [
        "jdbc:h2:mem:test",
        "jdbc:postgresql://app:hunter2@h/shop",
        "jdbc:mysql://h/shop?password=hunter2",
        "${DB_URL}",
        "",
    ],
)
def test_a_url_that_cannot_be_translated_is_noted_without_its_secrets(tmp_path, url):
    root = _project(tmp_path, f"flyway.url={url}\n")

    found = read_project(str(root), "flyway.conf")

    assert any("connection" in note for note in found.notes)
    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)


def test_credentials_inside_a_translatable_url_are_dropped(tmp_path):
    root = _project(
        tmp_path, "flyway.url=jdbc:postgresql://h:5432/shop?user=app&password=hunter2\n"
    )

    found = read_project(str(root), "flyway.conf")

    assert found.form.connection.database == "shop"
    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)


@pytest.mark.parametrize(
    "url",
    [
        # SQL Server quotes a value holding ";" in braces: the password is "x;database=hunter2".
        "jdbc:sqlserver://h:1433;password={x;database=hunter2};databaseName=shop",
        "jdbc:sqlserver://h:1433;databaseName=shop;password=hunter2",
        "jdbc:sqlserver://h:abc;password={x;hunter2}",
        "jdbc:oracle:thin:app/hunter2@h:1521/X",
        "jdbc:snowflake://acme.snowflakecomputing.com/?db=SHOP&password=hunter2",
        "jdbc:h2:mem:test;PASSWORD=hunter2",
        "jdbc:h2:mem:test;secret=hunter2",
        "jdbc:db2://h:50000/SHOP:password=hunter2;",
        "jdbc:postgresql://app:1234@h/hunter2x",
    ],
)
def test_no_url_shape_lets_a_password_through(tmp_path, url):
    root = _project(tmp_path, f"flyway.url={url}\n")

    found = read_project(str(root), "flyway.conf")

    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)


def test_a_user_holding_a_password_is_not_copied(tmp_path):
    root = _project(tmp_path, "flyway.url=jdbc:postgresql://h/shop\nflyway.user=app:hunter2\n")

    found = read_project(str(root), "flyway.conf")

    assert found.form.connection.username == ""
    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)
    assert any("user" in note for note in found.notes)


def test_a_toml_value_that_is_not_text_is_not_copied(tmp_path):
    text = (
        '[environments.default]\nurl = { password = "hunter2" }\n'
        'user = { name = "app", password = "hunter2" }\nschemas = [{ password = "hunter2" }]\n'
        'password = "hunter2"\n'
    )
    root = _project(tmp_path, text, name="flyway.toml")

    found = read_project(str(root), "flyway.toml")

    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)


def test_another_toml_environment_s_password_is_not_copied(tmp_path):
    text = (
        '[flyway]\nenvironment = "dev"\n'
        '[environments.dev]\nurl = "jdbc:mysql://h/shop"\n'
        '[environments.prod]\nurl = "jdbc:mysql://p/shop"\npassword = "hunter2"\n'
    )
    root = _project(tmp_path, text, name="flyway.toml")

    found = read_project(str(root), "flyway.toml")

    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)
    assert not any("password" in note for note in found.notes)


@pytest.mark.parametrize(
    "line",
    [
        "flyway.url=jdbc:postgresql://" + "a" * 200_000,
        "flyway.url=jdbc:postgresql://h:" + "1" * 200_000,
        "flyway.url=jdbc:sqlserver://h" + ";" * 100_000 + "=" * 100_000,
        "flyway.url=jdbc:sqlserver://h" + ";a=" * 66_000 + "{",
        "flyway.url=jdbc:oracle:thin:@" + "a1:" * 66_000,
        "flyway.url=jdbc:oracle:thin:@//h:1521/" + "X" * 200_000 + "!",
        "flyway.url=jdbc:snowflake://" + "a." * 100_000 + "!",
        "flyway.url=jdbc:snowflake://a/?" + "&" * 200_000,
        "flyway.url=jdbc:sqlite:" + "?" * 200_000,
        "flyway.url=" + "://x:" * 40_000,
        "flyway.locations=" + "filesystem:," * 16_000,
        "flyway.user=" + "a:" * 100_000,
        "flyway.table=" + "a" * 200_000,
        "x" * 200_000,
    ],
)
def test_a_hostile_line_is_read_quickly(tmp_path, monkeypatch, line):
    monkeypatch.setattr(flyway, "MAX_BYTES", 400_000)
    root = _project(tmp_path, line[:200_000] + "\n")

    started = time.perf_counter()
    read_project(str(root), "flyway.conf")

    assert time.perf_counter() - started < 1


@pytest.mark.parametrize(
    "locations, folders, directory, noted",
    [
        ("filesystem:sql", ("sql",), "./sql", False),
        ("filesystem:./db/migrations", ("db/migrations",), "./db/migrations", False),
        ("filesystem:sql,filesystem:more", ("sql", "more"), "./sql", True),
        (
            "classpath:db/migration",
            ("src/main/resources/db/migration",),
            "./src/main/resources/db/migration",
            False,
        ),
        ("classpath:db/migration", (), "./migrations", True),
        (
            "",
            ("src/main/resources/db/migration",),
            "./src/main/resources/db/migration",
            False,
        ),
        ("", (), "./migrations", True),
        ("filesystem:${MIGRATIONS}", (), "./migrations", True),
    ],
)
def test_locations(tmp_path, locations, folders, directory, noted):
    line = f"flyway.locations={locations}\n" if locations else ""
    root = _project(tmp_path, "flyway.url=jdbc:sqlite:legacy.db\n" + line, folders=folders)

    found = read_project(str(root), "flyway.conf")

    assert found.form.migrations_directory == directory
    assert any("migrations folder" in note for note in found.notes) is noted


def test_defaults(tmp_path):
    root = _project(tmp_path, "flyway.url=jdbc:sqlite:legacy.db\nflyway.defaultSchema=main\n")

    found = read_project(str(root), "flyway.conf")

    assert found.table == DEFAULT_TABLE
    assert found.form.connection.password.mode == "none"


@pytest.mark.parametrize("url", ["jdbc:mysql://h/shop", "jdbc:mongodb://h/shop"])
def test_an_engine_without_a_schema_field_gets_no_schema(tmp_path, url):
    root = _project(tmp_path, f"flyway.url={url}\nflyway.schemas=shop\nflyway.user=app\n")

    connection = read_project(str(root), "flyway.conf").form.connection

    assert (connection.schema_, connection.username) == ("", "app")


def test_an_unusable_table_name_falls_back_with_a_note(tmp_path):
    root = _project(tmp_path, "flyway.url=jdbc:sqlite:legacy.db\nflyway.table=bad name; drop\n")

    found = read_project(str(root), "flyway.conf")

    assert found.table == DEFAULT_TABLE
    assert any("history table" in note for note in found.notes)


TOML = """\
[flyway]
locations = ["filesystem:sql"]
table = "fw_history"
environment = "dev"

[environments.dev]
url = "jdbc:mysql://dev-host:3306/shop"
user = "app"
password = "hunter2"
schemas = ["shop"]

[environments.prod]
url = "jdbc:mysql://prod-host:3306/shop"
"""


def test_reads_a_toml_file(tmp_path):
    root = _project(tmp_path, TOML, name="flyway.toml")

    found = read_project(str(root), "flyway.toml")

    assert found.table == "fw_history"
    assert found.form.engine == "mysql"
    assert (found.form.connection.host, found.form.connection.username) == ("dev-host", "app")
    assert found.form.migrations_directory == "./sql"
    assert "hunter2" not in found.form.model_dump_json() + " ".join(found.notes)


def test_a_toml_without_a_named_environment_uses_default(tmp_path):
    root = _project(
        tmp_path, '[environments.default]\nurl = "jdbc:postgresql://h/shop"\n', name="flyway.toml"
    )

    assert read_project(str(root), "flyway.toml").form.connection.host == "h"


def test_a_file_in_a_sub_folder_puts_the_project_there(tmp_path):
    root = tmp_path / "mono"
    (root / "services" / "billing" / "sql").mkdir(parents=True)
    (root / "services" / "billing" / "flyway.conf").write_text(
        "flyway.url=jdbc:sqlite:b.db\nflyway.locations=filesystem:sql\n"
    )

    found = read_project(str(root), "services/billing/flyway.conf")

    assert found.folder == str((root / "services" / "billing").resolve())
    assert found.form.migrations_directory == "./sql"


@pytest.mark.parametrize(
    "relative",
    ["../flyway.conf", "dblift.yaml", "sql", "missing/flyway.conf", "", "/etc/flyway.conf"],
)
def test_refuses_anything_but_a_flyway_file_inside_the_folder(tmp_path, relative):
    root = _project(tmp_path, CONF)
    (tmp_path / "flyway.conf").write_text(CONF)
    (root / "dblift.yaml").write_text("database: {}\n")

    with pytest.raises(FlywayError):
        read_project(str(root), relative)


def test_refuses_a_link_out_of_the_folder(tmp_path):
    outside = tmp_path / "outside.conf"
    outside.write_text(CONF)
    root = tmp_path / "legacy"
    root.mkdir()
    os.symlink(outside, root / "flyway.conf")

    with pytest.raises(FlywayError):
        read_project(str(root), "flyway.conf")


def test_refuses_a_flyway_named_folder(tmp_path):
    root = tmp_path / "legacy"
    (root / "flyway.conf").mkdir(parents=True)

    with pytest.raises(FlywayError):
        read_project(str(root), "flyway.conf")


def test_refuses_a_huge_file(tmp_path, monkeypatch):
    monkeypatch.setattr(flyway, "MAX_BYTES", 20)
    root = _project(tmp_path, CONF)

    with pytest.raises(FlywayError, match="too large"):
        read_project(str(root), "flyway.conf")


def test_a_broken_toml_says_where_without_quoting_the_file(tmp_path):
    root = _project(tmp_path, 'password = "hunter2\n[oops', name="flyway.toml")

    with pytest.raises(FlywayError) as raised:
        read_project(str(root), "flyway.toml")

    assert "hunter2" not in str(raised.value)


@pytest.mark.parametrize(
    "text",
    [
        'password = "hunter2"\npassword = "hunter2"\n',
        'a = "x"\n[a]\npassword = "hunter2"\n',
        "password = hunter2\n",
        'password = "\\q hunter2"\n',
        "password = 0xhunter2\n",
    ],
)
def test_no_toml_error_quotes_the_file(tmp_path, text):
    root = _project(tmp_path, text, name="flyway.toml")

    with pytest.raises(FlywayError) as raised:
        read_project(str(root), "flyway.toml")

    assert "hunter2" not in str(raised.value)
    assert "line" in str(raised.value) or "end of" in str(raised.value)


def test_table_beside_a_config(tmp_path):
    root = _project(tmp_path, CONF)
    config = root / "dblift.yaml"

    assert table_beside(str(config)) == "schema_version"
    (root / "flyway.conf").write_text("flyway.url=jdbc:sqlite:x.db\n")
    assert table_beside(str(config)) == DEFAULT_TABLE
    (root / "flyway.conf").unlink()
    assert table_beside(str(config)) is None
    (root / "flyway.toml").write_text("not [ toml")
    assert table_beside(str(config)) == DEFAULT_TABLE


def test_table_beside_does_not_follow_a_link_out_of_the_folder(tmp_path):
    outside = tmp_path / "outside.conf"
    outside.write_text("flyway.table=elsewhere\n")
    root = tmp_path / "legacy"
    root.mkdir()
    os.symlink(outside, root / "flyway.conf")

    assert table_beside(str(root / "dblift.yaml")) == DEFAULT_TABLE
