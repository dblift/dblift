"""Database file locators and migration paths a configuration file cannot carry are refused.

A relative file URL is anchored to the configuration file's folder; a ``?`` in that folder would
be read back as a query string and open another file. A ``scheme://`` value no secrets provider
handles, and an empty ``database`` file locator, were opened as literal paths or failed unnamed.
"""

import re
from argparse import Namespace

import pytest
import yaml
from sqlalchemy.engine import make_url

from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import DbliftConfig, load_config
from dblift.config.errors import ConfigurationError
from dblift.config.file_path_anchoring import anchor_file_data
from dblift.config.secrets import AbstractSecretsProvider
from dblift.config.secrets import _registry as secrets_registry
from dblift.config.secrets._resolver import clear_cache

pytestmark = pytest.mark.unit

FILE_ENGINES = ["sqlite", "duckdb"]


class _SsmStub(AbstractSecretsProvider):
    scheme = "aws-ssm"

    def __init__(self, config=None):
        pass

    def is_available(self):
        return True

    def resolve(self, uri):
        return "x.db"


@pytest.fixture
def ssm_provider(monkeypatch):
    monkeypatch.setitem(secrets_registry._providers, "aws-ssm", _SsmStub)
    clear_cache()
    yield
    clear_cache()


def _write(folder, body):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "c.yaml"
    path.write_text(yaml.safe_dump(body))
    return str(path)


def _load(tmp_path, database, **extra):
    return load_config(_write(tmp_path / "proj", {"database": database, **extra}))


class TestQuestionMarkInTheConfigurationFolder:
    @pytest.mark.parametrize("engine", FILE_ENGINES)
    def test_a_relative_file_url_is_refused(self, tmp_path, engine):
        data = {
            "database": {"url": f"{engine}:///rel.db"},
            "environments": {"dev": {"database": {"url": f"{engine}:///rel.db"}}},
        }
        with pytest.raises(ConfigurationError, match=r"database\.url.*'\?'.*database\.path"):
            anchor_file_data(data, tmp_path / "q?dir")

    @pytest.mark.parametrize("engine", FILE_ENGINES)
    def test_load_config_and_the_builder_refuse_it(self, tmp_path, engine):
        path = _write(tmp_path / "q?dir", {"database": {"url": f"{engine}:///rel.db"}})
        with pytest.raises(ConfigurationError, match=r"database\.url.*'\?'"):
            load_config(path)
        with pytest.raises(ConfigurationError, match=r"database\.url.*'\?'"):
            ConfigBuilder.build(file_path=path)

    @pytest.mark.parametrize("key", ["path", "database"])
    def test_a_duckdb_file_name_is_refused(self, tmp_path, key):
        path = _write(tmp_path / "q?dir", {"database": {"type": "duckdb", key: "rel.db"}})
        with pytest.raises(ConfigurationError, match=r"'\?'"):
            load_config(path)

    def test_an_absolute_duckdb_path_is_refused(self):
        with pytest.raises(ConfigurationError, match=r"'\?'"):
            DbliftConfig.from_dict({"database": {"type": "duckdb", "path": "/a/q?dir/x.db"}})

    @pytest.mark.parametrize("key", ["path", "database"])
    def test_sqlite_file_names_are_anchored_into_the_folder(self, tmp_path, key):
        path = _write(tmp_path / "q?dir", {"database": {"type": "sqlite", key: "rel.db"}})
        config = load_config(path)
        assert config.database.path == str((tmp_path / "q?dir").resolve() / "rel.db")

    @pytest.mark.parametrize("engine", FILE_ENGINES)
    @pytest.mark.parametrize("folder", ["q#dir", "q dir", "q%20dir", "q&dir", "q+dir"])
    def test_other_special_characters_still_anchor(self, tmp_path, engine, folder):
        data = {"database": {"url": f"{engine}:///rel.db"}}
        anchor_file_data(data, tmp_path / folder)
        assert make_url(data["database"]["url"]).database == str(
            (tmp_path / folder).resolve() / "rel.db"
        )

    @pytest.mark.parametrize(
        "database",
        [
            {"url": "duckdb:///md:my_db?motherduck_token=t"},
            {"url": "duckdb:////abs/x.db?threads=2"},
            {"type": "duckdb", "database": "md:my_db?motherduck_token=t"},
            {"type": "duckdb", "path": "md:my_db?motherduck_token=t"},
        ],
    )
    def test_a_query_string_the_user_wrote_is_not_refused(self, tmp_path, database):
        assert _load(tmp_path, database).database.type == "duckdb"


@pytest.mark.usefixtures("ssm_provider")
class TestUnresolvedReferenceScheme:
    @pytest.mark.parametrize("key", ["path", "database"])
    def test_a_sqlite_file_name_is_refused(self, tmp_path, key):
        with pytest.raises(
            ConfigurationError,
            match=rf"database\.{key}: unresolved reference 'secret://x/db#x' "
            r"\(no secrets provider handles scheme 'secret'\)",
        ):
            _load(tmp_path, {"type": "sqlite", key: "secret://x/db#x"})

    def test_a_sqlite_url_database_is_refused(self, tmp_path):
        with pytest.raises(ConfigurationError, match=r"database\.url: unresolved reference"):
            _load(tmp_path, {"url": "sqlite:///secret://x/db"})

    def test_the_builder_refuses_it_too(self, tmp_path):
        path = _write(tmp_path, {"database": {"type": "sqlite", "path": "secret://x/db"}})
        with pytest.raises(ConfigurationError, match="no secrets provider handles scheme"):
            ConfigBuilder.build(file_path=path)

    @pytest.mark.parametrize(
        "database",
        [
            {"type": "sqlite", "path": "aws-ssm://p/db"},
            {"type": "sqlite", "database": "aws-ssm://p/db"},
            {"url": "sqlite:///aws-ssm://p/db"},
            {"type": "sqlite", "path": "file:rel.db?mode=ro"},
            {"type": "sqlite", "path": "file:///abs/rel.db"},
            {"type": "duckdb", "path": "secret://x/db"},
            {"type": "duckdb", "database": "s3://bucket/db"},
            {"type": "duckdb", "path": "md:my_db"},
        ],
    )
    def test_registered_schemes_and_locators_are_left_alone(self, tmp_path, database):
        _load(tmp_path, database)

    @pytest.mark.parametrize("value", ["secret://x/migs", "s3://bucket/migs"])
    @pytest.mark.parametrize(
        "migrations",
        [
            ("migrations.directory", lambda v: {"directory": v}),
            ("migrations.directories[1]", lambda v: {"directories": ["a", v]}),
            ("migrations.directories[0]", lambda v: {"directories": [{"path": v}]}),
            ("migrations.directories[0]", lambda v: {"directories": [{"directory": v}]}),
        ],
    )
    def test_a_migrations_directory_is_refused(self, tmp_path, value, migrations):
        key, build = migrations
        scheme = value.split("://")[0]
        with pytest.raises(
            ConfigurationError,
            match=rf"{re.escape(key)}: unresolved reference "
            rf"'{value}' \(no secrets provider handles scheme '{scheme}'\)",
        ):
            _load(tmp_path, {"type": "sqlite", "path": "x.db"}, migrations=build(value))

    def test_a_registered_scheme_directory_is_left_alone(self, tmp_path):
        _load(tmp_path, {"type": "sqlite", "path": "x.db"}, migrations={"directory": "aws-ssm://p"})

    def test_only_the_selected_environment_is_read(self, tmp_path):
        body = {
            "database": {"type": "sqlite", "path": "x.db"},
            "environments": {
                "dev": {"database": {"path": "secret://x/db"}},
                "prod": {"database": {"path": "prod.db"}},
            },
        }
        path = _write(tmp_path, body)
        load_config(path, Namespace(env="prod", command="info"))
        with pytest.raises(ConfigurationError, match=r"environments\.dev\.database\.path"):
            load_config(path, Namespace(env="dev", command="info"))

    def test_an_environment_value_overrides_the_root_one(self, tmp_path):
        body = {
            "database": {"type": "sqlite", "path": "secret://x/db"},
            "environments": {"dev": {"database": {"path": "dev.db"}}},
        }
        path = _write(tmp_path, body)
        load_config(path, Namespace(env="dev", command="info"))
        with pytest.raises(ConfigurationError, match=r"database\.path: unresolved"):
            load_config(path)


class TestEmptyDatabaseFileLocator:
    @pytest.fixture(autouse=True)
    def _unset(self, monkeypatch):
        monkeypatch.delenv("Q5B_NOT_SET", raising=False)

    @pytest.mark.parametrize("key", ["path", "database", "url"])
    def test_an_unset_placeholder_names_the_key(self, tmp_path, key):
        with pytest.raises(ConfigurationError, match=rf"database\.{key} is empty.*\$\{{VAR\}}"):
            _load(tmp_path, {"type": "sqlite", key: "${Q5B_NOT_SET}"})

    def test_the_builder_names_the_key_too(self, tmp_path):
        path = _write(tmp_path, {"database": {"type": "duckdb", "path": "${Q5B_NOT_SET}"}})
        with pytest.raises(ConfigurationError, match=r"database\.path is empty"):
            ConfigBuilder.build(file_path=path)

    def test_an_environment_block_is_named(self, tmp_path):
        body = {
            "database": {"type": "sqlite", "path": "x.db"},
            "environments": {"dev": {"database": {"path": "${Q5B_NOT_SET}"}}},
        }
        path = _write(tmp_path, body)
        load_config(path)
        with pytest.raises(ConfigurationError, match=r"environments\.dev\.database\.path is empty"):
            load_config(path, Namespace(env="dev", command="info"))

    @pytest.mark.parametrize(
        "database",
        [
            {"type": "sqlite", "path": "${Q5B_NOT_SET}", "url": "sqlite:///x.db"},
            {"type": "sqlite", "path": "${Q5B_NOT_SET}", "database": "x.db"},
            {"type": "sqlite", "path": "x.db", "database": "${Q5B_NOT_SET}"},
            {"url": "postgresql+psycopg://u:p@h/d", "database": "${Q5B_NOT_SET}"},
        ],
    )
    def test_an_empty_key_next_to_a_usable_locator_is_not_refused(self, tmp_path, database):
        _load(tmp_path, database)
