"""Relative paths written in a configuration file resolve against that file's folder."""

from argparse import Namespace
from pathlib import Path

import pytest
import yaml
from sqlalchemy.engine import make_url

from dblift.api.client import DBLiftClient
from dblift.cli._config_helpers import _resolve_scripts_directories
from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import ENV_PLACEHOLDER_PATTERN, DbliftConfig, load_config
from dblift.config.file_path_anchoring import anchor_file_data
from dblift.config.path_anchoring import anchor_config_paths

pytestmark = pytest.mark.unit


@pytest.fixture
def layout(tmp_path, monkeypatch):
    """A project folder holding the file, and a different working directory."""
    project = tmp_path / "proj"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return project, elsewhere


def _write(project: Path, body: dict) -> str:
    path = project / "dblift.yaml"
    path.write_text(yaml.safe_dump(body))
    return str(path)


def _args(config_path: str, **extra) -> Namespace:
    return Namespace(config=config_path, command="info", **{"scripts_list": None, **extra})


class TestLoadConfig:
    def test_migrations_directory(self, layout):
        project, _ = layout
        config = load_config(
            _write(
                project,
                {
                    "database": {"url": "sqlite:///:memory:"},
                    "migrations": {"directory": "migrations"},
                },
            )
        )
        assert Path(config.migrations.directory) == project / "migrations"

    def test_additional_migrations_directories(self, layout):
        project, _ = layout
        config = load_config(
            _write(
                project,
                {
                    "database": {"url": "sqlite:///:memory:"},
                    "migrations": {
                        "directory": "a",
                        "directories": ["b", {"path": "c", "recursive": False}],
                    },
                },
            )
        )
        paths = [Path(d.path) for d in config.migrations.get_directory_configs()]
        assert paths == [project / "b", project / "c"]
        assert not config.migrations.get_directory_configs()[1].recursive

    def test_sqlite_url(self, layout):
        project, _ = layout
        config = load_config(_write(project, {"database": {"url": "sqlite:///rel.db"}}))
        assert Path(config.database.path) == project / "rel.db"

    def test_sqlite_url_keeps_query_and_absolute_form(self, layout, tmp_path):
        project, _ = layout
        absolute = tmp_path / "abs.db"
        config = load_config(_write(project, {"database": {"url": f"sqlite:///{absolute}"}}))
        assert Path(config.database.path) == absolute
        config = load_config(_write(project, {"database": {"url": "sqlite:///rel.db?mode=rw"}}))
        assert Path(config.database.path) == project / "rel.db"

    def test_duckdb_url(self, layout):
        project, _ = layout
        config = load_config(_write(project, {"database": {"url": "duckdb:///rel.db"}}))
        assert Path(config.database.path) == project / "rel.db"
        assert make_url(config.database.url).database == str(project.resolve() / "rel.db")

    def test_duckdb_url_in_an_environment_block(self, layout):
        project, _ = layout
        path = _write(project, {"environments": {"dev": {"database": {"url": "duckdb:///rel.db"}}}})
        config = load_config(path, Namespace(env="dev"))
        assert make_url(config.database.url).database == str(project.resolve() / "rel.db")

    def test_duckdb_url_flag_stays_relative_to_the_working_directory(self, layout):
        project, _ = layout
        path = _write(project, {"database": {"url": "duckdb:///rel.db"}})
        config = load_config(path, Namespace(db_url="duckdb:///cli.db", command="info"))
        assert make_url(config.database.url).database == "cli.db"

    @pytest.mark.parametrize("db_type", ["sqlite", "duckdb"])
    def test_database_key(self, layout, db_type):
        project, _ = layout
        config = load_config(_write(project, {"database": {"type": db_type, "database": "rel.db"}}))
        assert Path(config.database.path) == project / "rel.db"

    def test_sqlite_memory_is_untouched(self, layout):
        project, _ = layout
        config = load_config(_write(project, {"database": {"url": "sqlite:///:memory:"}}))
        assert config.database.path == ":memory:"

    def test_sqlite_path_key(self, layout):
        project, _ = layout
        config = load_config(_write(project, {"database": {"type": "sqlite", "path": "rel.db"}}))
        assert Path(config.database.path) == project / "rel.db"

    def test_logging_directory(self, layout):
        project, _ = layout
        config = load_config(
            _write(
                project,
                {"database": {"url": "sqlite:///:memory:"}, "logging": {"directory": "logs"}},
            )
        )
        assert Path(config.logging.directory) == project / "logs"

    def test_root_log_dir(self, layout):
        project, _ = layout
        config = load_config(
            _write(project, {"database": {"url": "sqlite:///:memory:"}, "log_dir": "logs"})
        )
        assert Path(config.log_dir) == project / "logs"

    def test_environment_block(self, layout):
        project, _ = layout
        path = _write(
            project,
            {
                "database": {"url": "sqlite:///:memory:"},
                "environments": {"dev": {"migrations": {"directory": "dev_migrations"}}},
            },
        )
        config = load_config(path, Namespace(env="dev"))
        assert Path(config.migrations.directory) == project / "dev_migrations"

    def test_absolute_paths_are_kept(self, layout, tmp_path):
        project, _ = layout
        absolute = tmp_path / "elsewhere_abs"
        config = load_config(
            _write(
                project,
                {
                    "database": {"url": "sqlite:///:memory:"},
                    "migrations": {"directory": str(absolute)},
                },
            )
        )
        assert Path(config.migrations.directory) == absolute

    def test_command_line_values_stay_relative_to_the_working_directory(self, layout):
        project, elsewhere = layout
        path = _write(
            project,
            {
                "database": {"url": "sqlite:///rel.db"},
                "migrations": {"directory": "migrations"},
                "logging": {"directory": "logs"},
            },
        )
        args = Namespace(
            db_url="sqlite:///cli.db",
            migrations_dir="cli_migrations",
            log_dir="cli_logs",
            command="info",
        )
        config = load_config(path, args)
        assert Path(config.database.path) == Path("cli.db")
        assert Path(config.migrations.directory) == Path("cli_migrations")
        assert Path(config.log_dir) == Path("cli_logs")


class TestConfigBuilder:
    def test_build_anchors_file_paths_but_not_keyword_overrides(self, layout):
        project, _ = layout
        path = _write(
            project,
            {
                "database": {"url": "sqlite:///rel.db"},
                "migrations": {"directory": "migrations"},
                "logging": {"directory": "logs"},
            },
        )
        config = ConfigBuilder.build(file_path=path)
        assert Path(config.database.path) == project / "rel.db"
        assert Path(config.migrations.directory) == project / "migrations"
        assert Path(config.logging.directory) == project / "logs"

        overridden = ConfigBuilder.build(file_path=path, database_url="sqlite:///kw.db")
        assert Path(overridden.database.path) == Path("kw.db")


class TestResolveScriptsDirectories:
    def _resolve(self, project, body, **args):
        path = _write(project, body)
        config = load_config(path)
        namespace = _args(path, **args)
        return _resolve_scripts_directories(namespace, config, None, ["info"])

    def test_primary_directory_is_resolved_against_the_file(self, layout):
        project, _ = layout
        body = {
            "database": {"url": "sqlite:///:memory:"},
            "migrations": {"directory": "migrations"},
        }
        scripts_dir, additional, _, _ = self._resolve(project, body)
        assert scripts_dir == project / "migrations"
        assert additional == []

    def test_additional_directories_are_resolved_against_the_file(self, layout):
        project, _ = layout
        body = {
            "database": {"url": "sqlite:///:memory:"},
            "migrations": {"directory": "a", "directories": ["b", "c"]},
        }
        scripts_dir, additional, _, _ = self._resolve(project, body)
        assert scripts_dir == project / "b"
        assert additional == [project / "c"]

    def test_scripts_flag_stays_relative_to_the_working_directory(self, layout):
        project, elsewhere = layout
        (elsewhere / "cli_scripts").mkdir()
        body = {
            "database": {"url": "sqlite:///:memory:"},
            "migrations": {"directory": "migrations"},
        }
        scripts_dir, _, _, _ = self._resolve(project, body, scripts_list=["cli_scripts"])
        assert scripts_dir == (elsewhere / "cli_scripts").resolve()


class TestClientFromConfigFile:
    def _project(self, project: Path, url: str = "sqlite:///rel.db") -> str:
        (project / "migrations").mkdir()
        (project / "migrations" / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);\n")
        return _write(
            project,
            {
                "database": {"url": url},
                "migrations": {"directory": "migrations"},
                "logging": {"directory": "logs", "file": "dblift.log"},
            },
        )

    @pytest.mark.parametrize("url", ["sqlite:///rel.db", "duckdb:///rel.db"])
    def test_from_config_file_resolves_against_the_file_by_default(self, layout, url):
        project, elsewhere = layout
        path = self._project(project, url)

        with DBLiftClient.from_config_file(path) as client:
            assert [m.script for m in client.info().migrations] == ["V1__t.sql"]
            assert client.migrate().success

        assert (project / "rel.db").exists()
        assert (project / "logs").is_dir()
        assert list(elsewhere.iterdir()) == []


class TestAnchorFileData:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+psycopg://u:p@host/db",
            "sqlite:///:memory:",
            "sqlite:///file:rel.db?uri=true",
            "sqlite:////abs/x.db",
            "sqlite://",
            "sqlite://[bad",
            "duckdb:///:memory:",
            "duckdb:////abs/x.db",
            "duckdb://",
            "duckdb:///md:my_db",
            "duckdb:///MD:my_db",
            "duckdb:///motherduck:my_db",
            "duckdb:///sqlite:legacy.db",
            "duckdb:///ducklake:meta.ducklake",
            "postgresql://h/db",
            "postgresql://h/rel.db",
            "mysql+pymysql://u:p@h/rel.db",
        ],
    )
    def test_urls_that_name_no_relative_file_are_unchanged(self, tmp_path, url):
        data = {"database": {"url": url}}
        anchor_file_data(data, tmp_path)
        assert data == {"database": {"url": url}}

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("duckdb:///rel.db", "duckdb:///{base}/rel.db"),
            ("duckdb:///sub/rel.db", "duckdb:///{base}/sub/rel.db"),
            ("sqlite:///db:2024.db", "sqlite:///{base}/db:2024.db"),
            ("sqlite:///FILE:up.db", "sqlite:///{base}/FILE:up.db"),
            ("sqlite3:///backup:1.db", "sqlite3:///{base}/backup:1.db"),
            ("duckdb+duckdb_engine:///rel.db", "duckdb+duckdb_engine:///{base}/rel.db"),
            ("duckdb:///rel.db?threads=2", "duckdb:///{base}/rel.db?threads=2"),
        ],
    )
    def test_a_relative_file_url_is_anchored(self, tmp_path, url, expected):
        base = tmp_path.resolve().as_posix()
        data = {
            "database": {"url": url},
            "environments": {"dev": {"database": {"url": url}}},
        }
        anchor_file_data(data, tmp_path)
        assert data["database"]["url"] == expected.format(base=base)
        assert data["environments"]["dev"]["database"]["url"] == expected.format(base=base)

    @pytest.mark.parametrize("db_type", ["sqlite", "sqlite3", "duckdb", "DuckDB"])
    def test_a_relative_database_key_of_a_file_based_dialect_is_anchored(self, tmp_path, db_type):
        data = {
            "database": {"type": db_type, "database": "rel.db"},
            "environments": {"dev": {"database": {"database": "env.db"}}},
        }
        anchor_file_data(data, tmp_path)
        assert data["database"]["database"] == str(tmp_path.resolve() / "rel.db")
        assert data["environments"]["dev"]["database"]["database"] == str(
            tmp_path.resolve() / "env.db"
        )

    @pytest.mark.parametrize(
        "database",
        [
            {"type": "postgresql", "database": "mydb"},
            {"type": "mysql", "database": "rel.db"},
            {"database": "rel.db"},
            {"type": "sqlite", "database": ":memory:"},
            {"type": "sqlite", "database": "file:rel.db"},
            {"type": "duckdb", "database": "md:my_db"},
            {"type": "duckdb", "database": "sqlite:legacy.db"},
            {"type": "duckdb", "path": "md:my_db"},
            {"type": "duckdb", "path": "ducklake:meta.ducklake"},
            {"type": "sqlite", "path": "file:rel.db"},
            {"type": "duckdb", "database": "/abs/x.db"},
            {"type": "sqlite", "database": ""},
        ],
    )
    def test_a_database_key_that_names_no_relative_file_is_unchanged(self, tmp_path, database):
        data = {"database": dict(database)}
        anchor_file_data(data, tmp_path)
        assert data == {"database": database}

    def test_an_anchored_duckdb_url_keeps_the_file_the_driver_opens(self, tmp_path):
        data = {"database": {"url": "duckdb:///rel.db"}}
        anchor_file_data(data, tmp_path)
        assert make_url(data["database"]["url"]).database == str(tmp_path.resolve() / "rel.db")

    def test_sqlite3_alias_and_directory_alias_entries(self, tmp_path):
        data = {
            "database": {"url": "sqlite3:///rel.db"},
            "migrations": {"directories": [{"directory": "d", "recursive": False}, "", 3]},
        }
        anchor_file_data(data, tmp_path)
        assert make_url(data["database"]["url"]).database == str(tmp_path.resolve() / "rel.db")
        assert data["migrations"]["directories"] == [
            {"directory": str(tmp_path.resolve() / "d"), "recursive": False},
            "",
            3,
        ]


REFERENCES = [
    "secret://p/q#r",
    "s3://bucket/migrations",
    "git+ssh://host/repo",
    "${UNSET_DIR}",
    "${UNSET_DIR}/migrations",
    "${UNSET_DIR:-}",
    "${secret:p/q}",
    "${secret:p/q}/migrations",
    "db/${secret:p/q}/migrations",
    "HTTP://h/x",
]
# The loader expands a plain ``${VAR}`` itself; a form it cannot parse stays literal.
LEFT_LITERAL_BY_THE_LOADER = [v for v in REFERENCES if not ENV_PLACEHOLDER_PATTERN.search(v)]


def _every_anchored_key(value):
    """The same *value* under every key the module anchors, in the root and an environment."""

    def block():
        return {
            "migrations": {
                "directory": value,
                "directories": [value, {"path": value, "recursive": False}, {"directory": value}],
            },
            "database": {"path": value},
            "logging": {"directory": value, "file": value},
            "log_dir": value,
            "log_file": value,
        }

    return {**block(), "environments": {"dev": block()}}


class TestReferencesAreNotPaths:
    @pytest.mark.parametrize("value", REFERENCES)
    def test_every_anchored_key_keeps_a_reference_as_written(self, tmp_path, value):
        data = _every_anchored_key(value)
        expected = _every_anchored_key(value)
        anchor_file_data(data, tmp_path)
        assert data == expected

    @pytest.mark.parametrize("value", REFERENCES)
    def test_a_database_url_naming_a_reference_is_unchanged(self, tmp_path, value):
        for url in (value, f"sqlite:///{value}"):
            data = {"database": {"url": url}, "environments": {"dev": {"database": {"url": url}}}}
            anchor_file_data(data, tmp_path)
            assert data["database"]["url"] == url
            assert data["environments"]["dev"]["database"]["url"] == url

    @pytest.mark.parametrize("value", LEFT_LITERAL_BY_THE_LOADER)
    def test_loading_a_file_keeps_a_reference_as_written(self, layout, value):
        project, _ = layout
        body = _every_anchored_key(value)
        data = DbliftConfig.load_config_data_from_yaml(_write(project, body))
        assert data == body

    def test_a_scheme_must_start_the_value(self, tmp_path):
        data = {"log_dir": "dir/a://b"}
        anchor_file_data(data, tmp_path)
        assert data["log_dir"] == str(tmp_path.resolve() / "dir" / "a:" / "b")

    def test_a_relative_path_with_a_colon_but_no_scheme_is_still_a_path(self, tmp_path):
        data = {"migrations": {"directory": "db/migrations"}, "log_dir": "a:b/logs"}
        anchor_file_data(data, tmp_path)
        assert data["migrations"]["directory"] == str(tmp_path.resolve() / "db" / "migrations")
        assert data["log_dir"] == str(tmp_path.resolve() / "a:b" / "logs")

    def test_a_loaded_config_keeps_a_reference_as_written(self, tmp_path):
        config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": "x.db"}})
        config.migrations.directory = "secret://p/q"
        config.migrations.directories = ["${secret:p/q}"]
        config.log_dir = "secret://logs"
        anchor_config_paths(config, tmp_path)
        assert config.migrations.directory == "secret://p/q"
        assert config.migrations.directories == ["${secret:p/q}"]
        assert config.log_dir == "secret://logs"
