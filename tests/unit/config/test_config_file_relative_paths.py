"""Relative paths written in a configuration file resolve against that file's folder."""

from argparse import Namespace
from pathlib import Path

import pytest
import yaml
from sqlalchemy.engine import make_url

from dblift.api.client import DBLiftClient
from dblift.cli._config_helpers import _resolve_scripts_directories
from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import load_config
from dblift.config.file_path_anchoring import anchor_file_data

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
    def _project(self, project: Path) -> str:
        (project / "migrations").mkdir()
        (project / "migrations" / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);\n")
        return _write(
            project,
            {
                "database": {"url": "sqlite:///rel.db"},
                "migrations": {"directory": "migrations"},
                "logging": {"directory": "logs", "file": "dblift.log"},
            },
        )

    def test_from_config_file_resolves_against_the_file_by_default(self, layout):
        project, elsewhere = layout
        path = self._project(project)

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
        ],
    )
    def test_urls_that_name_no_relative_file_are_unchanged(self, tmp_path, url):
        data = {"database": {"url": url}}
        anchor_file_data(data, tmp_path)
        assert data == {"database": {"url": url}}

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
