import pytest
import yaml
from dblift_ui.configs import (
    ENGINES,
    MASK,
    ConfigError,
    ConfigForm,
    Connection,
    EnvironmentForm,
    Password,
    build_url,
    read_form,
    render,
    revision,
)


def _form(engine="postgresql", **connection):
    defaults = dict(
        host="db.example.com", port=5432, database="shop", username="app", schema="public"
    )
    defaults.update(connection)
    return ConfigForm(engine=engine, connection=Connection(**defaults))


def test_catalogue_lists_the_eleven_engines():
    assert [e.id for e in ENGINES] == [
        "postgresql",
        "mysql",
        "mariadb",
        "sqlserver",
        "oracle",
        "db2",
        "sqlite",
        "cockroachdb",
        "redshift",
        "snowflake",
        "mongodb",
    ]
    by_id = {e.id: e for e in ENGINES}
    assert by_id["sqlite"].fields == ("path",)
    assert "service_name" in by_id["oracle"].fields and "database" not in by_id["oracle"].fields
    assert {"account", "warehouse"} <= set(by_id["snowflake"].fields)
    assert by_id["sqlserver"].scheme == "mssql" and by_id["sqlserver"].port == 1433


@pytest.mark.parametrize(
    "engine, connection, url",
    [
        ("postgresql", dict(host="h", port=5432, database="shop"), "postgresql://h:5432/shop"),
        ("postgresql", dict(host="h", database="shop"), "postgresql://h/shop"),
        ("mysql", dict(host="h", port=3306, database="shop"), "mysql://h:3306/shop"),
        ("mariadb", dict(host="h", port=3306, database="shop"), "mariadb://h:3306/shop"),
        ("sqlserver", dict(host="h", port=1433, database="shop"), "mssql://h:1433/shop"),
        (
            "oracle",
            dict(host="h", port=1521, service_name="FREEPDB1"),
            "oracle://h:1521/?service_name=FREEPDB1",
        ),
        ("db2", dict(host="h", port=50000, database="SHOP"), "db2://h:50000/SHOP"),
        ("cockroachdb", dict(host="h", port=26257, database="shop"), "cockroachdb://h:26257/shop"),
        ("redshift", dict(host="h", port=5439, database="shop"), "redshift://h:5439/shop"),
        (
            "snowflake",
            dict(account="acme-xy1", database="shop", warehouse="WH"),
            "snowflake://acme-xy1/shop?warehouse=WH",
        ),
        ("snowflake", dict(account="acme-xy1", database="shop"), "snowflake://acme-xy1/shop"),
        ("mongodb", dict(host="h", port=27017, database="shop"), "mongodb://h:27017/shop"),
        ("postgresql", dict(host="h", database="my db/x"), "postgresql://h/my%20db%2Fx"),
    ],
)
def test_build_url(engine, connection, url):
    assert build_url(engine, Connection(**connection)) == url


@pytest.mark.parametrize(
    "engine, connection, message",
    [
        ("postgresql", dict(database="shop"), "host"),
        ("postgresql", dict(host="h"), "database"),
        ("postgresql", dict(host="bad host", database="d"), "host"),
        ("postgresql", dict(host="h@evil", database="d"), "host"),
        ("oracle", dict(host="h"), "service name"),
        ("snowflake", dict(database="d"), "account"),
        ("nope", dict(host="h", database="d"), "engine"),
    ],
)
def test_build_url_says_what_is_missing(engine, connection, message):
    with pytest.raises(ConfigError, match=message):
        build_url(engine, Connection(**connection))


def test_renders_a_new_config_with_a_placeholder_password():
    text = render(_form())

    assert yaml.safe_load(text) == {
        "database": {
            "url": "postgresql://db.example.com:5432/shop",
            "username": "app",
            "schema": "public",
            "password": "${DBLIFT_DB_PASSWORD}",
        },
        "migrations": {"directory": "./migrations"},
    }


def test_renders_sqlite_with_type_and_path():
    form = ConfigForm(
        engine="sqlite", connection=Connection(path="./dev.db", password=Password(mode="none"))
    )

    assert yaml.safe_load(render(form)) == {
        "database": {"type": "sqlite", "path": "./dev.db"},
        "migrations": {"directory": "./migrations"},
    }


def test_options_are_written_only_when_they_differ_from_the_defaults():
    form = _form()
    form.recursive = False
    form.log_level = "DEBUG"
    form.strict_mode = True
    form.clean_disabled = False

    data = yaml.safe_load(render(form))

    assert data["migrations"] == {"directory": "./migrations", "recursive": False}
    assert data["logging"] == {"level": "DEBUG"}
    assert data["strict_mode"] is True and data["clean_disabled"] is False


def test_literal_password_is_written_and_masked_in_a_preview():
    form = _form(password=Password(mode="literal", value="s3cret"))

    assert yaml.safe_load(render(form))["database"]["password"] == "s3cret"
    preview = render(form, mask=True)
    assert "s3cret" not in preview and yaml.safe_load(preview)["database"]["password"] == MASK


@pytest.mark.parametrize(
    "password, message",
    [
        (Password(mode="env", value="not a name"), "variable"),
        (Password(mode="env", value=""), "variable"),
        (Password(mode="literal", value=""), "password"),
        (Password(mode="keep"), "no saved password"),
    ],
)
def test_password_problems(password, message):
    with pytest.raises(ConfigError, match=message):
        render(_form(password=password))


EXISTING = """\
# Shop database
database:
  url: postgresql://old-host:5432/shop   # primary
  username: app
  password: hunter2
  connection_timeout: 15
migrations:
  directory: ./db/migrations
  table: shop_history
placeholders:
  owner: shop
"""


def test_editing_keeps_comments_unknown_keys_and_the_saved_password():
    form, notes = read_form(EXISTING)
    assert notes == []
    assert form.engine == "postgresql"
    assert (form.connection.host, form.connection.port, form.connection.database) == (
        "old-host",
        5432,
        "shop",
    )
    assert form.connection.password == Password(mode="keep", value="")
    assert form.migrations_directory == "./db/migrations"

    form.connection.host = "new-host"
    text = render(form, existing=EXISTING)

    assert "# Shop database" in text and "# primary" in text
    data = yaml.safe_load(text)
    assert data["database"] == {
        "url": "postgresql://new-host:5432/shop",
        "username": "app",
        "password": "hunter2",
        "connection_timeout": 15,
    }
    assert data["migrations"] == {"directory": "./db/migrations", "table": "shop_history"}
    assert data["placeholders"] == {"owner": "shop"}
    assert "hunter2" not in render(form, existing=EXISTING, mask=True)


def test_reading_never_returns_a_stored_password():
    form, _ = read_form(EXISTING)

    assert "hunter2" not in form.model_dump_json()


def test_reading_recognises_a_placeholder_password():
    form, _ = read_form("database:\n  url: mysql://h:3306/shop\n  password: ${SHOP_PW}\n")

    assert form.engine == "mysql"
    assert form.connection.password == Password(mode="env", value="SHOP_PW")


def test_a_placeholder_with_a_default_is_kept_not_shown():
    form, _ = read_form("database:\n  url: mysql://h/shop\n  password: ${SHOP_PW:-hunter2}\n")

    assert form.connection.password.mode == "keep"
    assert "hunter2" not in form.model_dump_json()


def test_reading_without_a_password():
    form, _ = read_form("database:\n  type: sqlite\n  path: ./dev.db\n")

    assert form.engine == "sqlite" and form.connection.path == "./dev.db"
    assert form.connection.password.mode == "none"


def test_loose_connection_keys_are_folded_into_the_url():
    existing = "database:\n  type: postgresql\n  host: h\n  port: 5433\n  database: shop\n  username: app\n  password: x\n"
    form, _ = read_form(existing)
    assert (form.connection.mode, form.connection.host, form.connection.port) == (
        "fields",
        "h",
        5433,
    )

    data = yaml.safe_load(render(form, existing=existing))

    assert data["database"] == {
        "type": "postgresql",
        "url": "postgresql://h:5433/shop",
        "username": "app",
        "password": "x",
    }


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://localhost:5432/dblift",
        "mssql+pymssql://localhost:1433/db?encrypt=false",
        "postgresql://h:5432/shop?sslmode=require",
        "weird://h/db",
    ],
)
def test_a_url_the_form_cannot_express_is_edited_raw_and_survives(url):
    existing = f"database:\n  url: {url}\n  username: app\n  password: x\n"
    form, notes = read_form(existing)

    assert form.connection.mode == "url" and form.connection.url == url
    assert len(notes) == 1 and "URL" in notes[0]
    assert yaml.safe_load(render(form, existing=existing))["database"]["url"] == url


def test_credentials_inside_a_url_are_masked_and_kept():
    existing = "database:\n  url: postgresql://app:hunter2@h:5432/shop\n"
    form, _ = read_form(existing)

    assert form.connection.mode == "url"
    assert form.connection.url == f"postgresql://app:{MASK}@h:5432/shop"
    assert "hunter2" not in form.model_dump_json()
    assert (
        yaml.safe_load(render(form, existing=existing))["database"]["url"]
        == "postgresql://app:hunter2@h:5432/shop"
    )
    assert "hunter2" not in render(form, existing=existing, mask=True)

    form.connection.url = "postgresql://app:n3w@other:5432/shop"
    assert (
        yaml.safe_load(render(form, existing=existing))["database"]["url"]
        == "postgresql://app:n3w@other:5432/shop"
    )


def test_a_masked_url_cannot_be_saved_into_a_new_file():
    form = ConfigForm(
        engine="postgresql",
        connection=Connection(mode="url", url=f"postgresql://app:{MASK}@h/shop"),
    )

    with pytest.raises(ConfigError, match="masked"):
        render(form)


ENVIRONMENTS = """\
database:
  url: postgresql://dev-host:5432/shop
  username: app
  password: ${DEV_PW}
environments:
  staging:
    database:
      url: postgresql://stg-host:5432/shop
      password: stg-secret
    logging:
      level: DEBUG
  prod:
    database:
      url: postgresql://prod-host:5432/shop
      password: ${PROD_PW}
"""


def test_environments_are_read_with_their_secrets_masked():
    form, _ = read_form(ENVIRONMENTS)

    assert [e.name for e in form.environments] == ["staging", "prod"]
    staging, prod = form.environments
    assert staging.connection.host == "stg-host" and staging.connection.password.mode == "keep"
    assert staging.connection.username == ""
    assert prod.connection.password == Password(mode="env", value="PROD_PW")
    assert "stg-secret" not in form.model_dump_json()


def test_environments_are_added_changed_and_removed():
    form, _ = read_form(ENVIRONMENTS)
    form.environments[0].connection.host = "staging.internal"
    del form.environments[1]
    form.environments.append(
        EnvironmentForm(
            name="qa",
            connection=Connection(
                host="qa-host",
                port=5432,
                database="shop",
                password=Password(mode="env", value="QA_PW"),
            ),
        )
    )

    data = yaml.safe_load(render(form, existing=ENVIRONMENTS))

    assert list(data["environments"]) == ["staging", "qa"]
    assert data["environments"]["staging"] == {
        "database": {"url": "postgresql://staging.internal:5432/shop", "password": "stg-secret"},
        "logging": {"level": "DEBUG"},
    }
    assert data["environments"]["qa"] == {
        "database": {"url": "postgresql://qa-host:5432/shop", "password": "${QA_PW}"}
    }
    masked = render(form, existing=ENVIRONMENTS, mask=True)
    assert "stg-secret" not in masked


def test_an_environment_with_empty_fields_inherits():
    form = _form()
    form.environments = [
        EnvironmentForm(
            name="ci", connection=Connection(password=Password(mode="env", value="CI_PW"))
        )
    ]

    assert yaml.safe_load(render(form))["environments"] == {
        "ci": {"database": {"password": "${CI_PW}"}}
    }


def test_removing_the_last_environment_removes_the_section():
    form, _ = read_form(ENVIRONMENTS)
    form.environments = []

    assert "environments" not in yaml.safe_load(render(form, existing=ENVIRONMENTS))


@pytest.mark.parametrize("name", ["", "has space", "a/b", "resolve", "-x"])
def test_environment_names_are_checked(name):
    form = _form()
    form.environments = [EnvironmentForm(name=name, connection=Connection())]

    with pytest.raises(ConfigError, match="environment"):
        render(form)


def test_duplicate_environment_names_are_refused():
    form = _form()
    form.environments = [
        EnvironmentForm(name="qa", connection=Connection()),
        EnvironmentForm(name="qa", connection=Connection()),
    ]

    with pytest.raises(ConfigError, match="twice"):
        render(form)


@pytest.mark.parametrize(
    "text", ["- a\n- b\n", "database: nope\n", "database:\n  password: a: b\n", ""]
)
def test_reading_a_config_that_is_not_one(text):
    with pytest.raises(ConfigError):
        read_form(text)


def test_reading_notes_a_secrets_section():
    _, notes = read_form("database:\n  url: mysql://h/shop\nsecrets:\n  provider: vault\n")

    assert any("secrets" in note for note in notes)


def test_revision_changes_with_the_text():
    assert revision("a") == revision("a") != revision("b")
    assert len(revision("a")) == 64


@pytest.mark.parametrize(
    "url, shown",
    [
        ("postgresql://app:p@ss@h:5432/shop", f"postgresql://app:{MASK}@h:5432/shop"),
        ("postgresql://app:pa/ss@h:5432/shop", f"postgresql://app:{MASK}@h:5432/shop"),
        ("postgresql://app@corp:hunter2@h/shop", f"postgresql://app@corp:{MASK}@h/shop"),
        ("postgresql://h:5432/shop?password=hunter2", f"postgresql://h:5432/shop?password={MASK}"),
        (
            "snowflake://acct/shop?warehouse=WH&PWD=hunter2",
            f"snowflake://acct/shop?warehouse=WH&PWD={MASK}",
        ),
    ],
)
def test_every_password_inside_a_url_is_masked_and_kept(url, shown):
    existing = f"database:\n  url: {url}\nenvironments:\n  qa:\n    database:\n      url: {url}\n"
    form, _ = read_form(existing)

    assert form.connection.mode == "url" and form.connection.url == shown
    assert form.environments[0].connection.url == shown
    assert "hunter2" not in form.model_dump_json() and "ss@" not in form.model_dump_json()
    data = yaml.safe_load(render(form, existing=existing))
    assert data["database"]["url"] == url and data["environments"]["qa"]["database"]["url"] == url
    masked = render(form, existing=existing, mask=True)
    assert "hunter2" not in masked and "ss@" not in masked


def test_a_password_that_reads_as_a_number_is_masked():
    existing = "database:\n  url: mysql://h/shop\n  password: 0\n"
    form, _ = read_form(existing)

    assert form.connection.password.mode == "keep"
    assert (
        yaml.safe_load(render(form, existing=existing, mask=True))["database"]["password"] == MASK
    )


def test_a_repeated_key_is_reported_without_its_values():
    with pytest.raises(ConfigError, match="line 3, column 3") as caught:
        read_form("database:\n  password: hunter2\n  password: other\n")

    assert "hunter2" not in str(caught.value) and "other" not in str(caught.value)


def test_an_environment_left_empty_stays_declared_without_an_empty_database():
    form = _form()
    form.environments = [
        EnvironmentForm(name="ci", connection=Connection(password=Password(mode="none")))
    ]

    assert yaml.safe_load(render(form))["environments"] == {"ci": {}}


def test_emptying_an_environment_drops_its_database_but_keeps_other_sections():
    form, _ = read_form(ENVIRONMENTS)
    form.environments[0].connection = Connection(password=Password(mode="none"))

    assert yaml.safe_load(render(form, existing=ENVIRONMENTS))["environments"]["staging"] == {
        "logging": {"level": "DEBUG"}
    }


def test_switching_from_sqlite_to_a_server_engine_drops_type_and_path():
    existing = "database:\n  type: sqlite\n  path: ./dev.db\n  busy_timeout: 5\n"

    assert yaml.safe_load(render(_form(), existing=existing))["database"] == {
        "url": "postgresql://db.example.com:5432/shop",
        "username": "app",
        "schema": "public",
        "password": "${DBLIFT_DB_PASSWORD}",
        "busy_timeout": 5,
    }


def test_a_type_naming_the_same_engine_is_kept():
    existing = "database:\n  type: PostgreSQL\n  url: postgresql://h:5432/shop\n"

    assert yaml.safe_load(render(_form(), existing=existing))["database"]["type"] == "PostgreSQL"


def test_switching_to_sqlite_drops_the_server_keys():
    existing = (
        "database:\n  type: postgresql\n  host: h\n  port: 5433\n  database: shop\n"
        "  username: app\n  password: x\n  connection_timeout: 15\n"
    )
    form = ConfigForm(
        engine="sqlite", connection=Connection(path="./dev.db", password=Password(mode="none"))
    )

    assert yaml.safe_load(render(form, existing=existing))["database"] == {
        "type": "sqlite",
        "path": "./dev.db",
        "connection_timeout": 15,
    }


def test_a_url_connection_leaves_type_and_path_alone():
    existing = (
        "database:\n  type: postgresql\n  path: ./unused\n  url: postgresql+psycopg://h/shop\n"
    )
    form, _ = read_form(existing)

    data = yaml.safe_load(render(form, existing=existing))["database"]
    assert (data["type"], data["path"]) == ("postgresql", "./unused")


def test_a_lower_case_level_survives_a_round_trip_as_written():
    existing = "database:\n  url: mysql://h/shop\nlogging:\n  level: warn\n"
    form, _ = read_form(existing)
    assert form.log_level == "WARN"

    form.connection.host = "other"
    assert "level: warn\n" in render(form, existing=existing)


@pytest.mark.parametrize("level", ["DEBUG", "info", "Warning", "WARN", "ERROR", "critical"])
def test_every_known_level_is_accepted(level):
    form = _form()
    form.log_level = level

    assert yaml.safe_load(render(form)).get("logging", {"level": "INFO"})["level"] == level.upper()


def test_an_unknown_level_in_the_file_survives_but_cannot_be_chosen():
    existing = "database:\n  url: mysql://h/shop\nlogging:\n  level: verbose\n"
    form, _ = read_form(existing)
    assert form.log_level == "VERBOSE"

    form.connection.host = "other"
    assert yaml.safe_load(render(form, existing=existing))["logging"] == {"level": "verbose"}
    form.log_level = "LOUD"
    with pytest.raises(ConfigError, match="log level"):
        render(form, existing=existing)
