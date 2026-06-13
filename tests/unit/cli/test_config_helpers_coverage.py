"""Coverage tests for cli/_config_helpers.py — missing lines.

Targets the uncovered line ranges:
  120-170  _build_args_namespace: multi-command path (len(commands) > 1)
  222, 225 _load_and_merge_config: table_name, installed_by branches
  269, 278-295 _validate_db_config: sqlite, cosmosdb, no-database branches
  303, 327 _validate_db_config: missing URL, baseline version default
  362, 364 _configure_logging: quiet flag, no_progress flag
  423-439  _resolve_scripts_directories: multiple dirs, recursive flag
  451-457  _resolve_scripts_directories: dir_recursive_map population
  460, 464 _resolve_scripts_directories: dir_recursive_map for first dir
  478      _resolve_scripts_directories: cli_recursive propagation
  525      _ensure_connection: ensure_connection / create_connection path
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from cli._config_helpers import (
    _build_args_namespace,
    _close_logs,
    _collect_placeholders,
    _ensure_connection,
    _extract_commands_from_argv,
    _load_and_merge_config,
    _resolve_scripts_directories,
    _validate_db_config,
    _validate_log_format_for_cli,
)

# ---------------------------------------------------------------------------
# _build_args_namespace — multi-command path (lines 119-170)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildArgsNamespace:
    """Tests for _build_args_namespace covering the len(commands) > 1 branch."""

    def _patch_parser(self, args_ns=None, unknown=None, has_error=False):
        """Return patches for create_parser and parse_with_selective_errors."""
        if args_ns is None:
            args_ns = SimpleNamespace(
                command="migrate",
                config=None,
                scripts_list=None,
                dry_run=False,
                log_dir="logs",
                log_format="text",
                log_level="info",
                log_file=None,
                database_url=None,
                database_username=None,
                database_password=None,
                database_schema=None,
                license_key=None,
            )
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = args_ns
        return mock_parser, args_ns, unknown or [], has_error

    def test_multi_command_parse_success(self):
        # Lines 119-170: len(commands) > 1 path
        mock_parser = MagicMock()
        expected_ns = SimpleNamespace(
            command="migrate",
            config=None,
            scripts_list=None,
            dry_run=False,
            log_dir="logs",
            log_format="text",
            log_level="info",
            log_file=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            license_key=None,
        )
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors",
                return_value=(expected_ns, [], False),
            ),
        ):
            args, unknown = _build_args_namespace(
                commands=["migrate", "info"], global_arguments=[], subcommand_args=[]
            )
        assert args is not None
        assert args.command == "migrate"

    def test_multi_command_validation_error_calls_sys_exit(self):
        # Lines 122-125: has_validation_error → sys.exit(2)
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch("cli._config_helpers.parse_with_selective_errors", return_value=(None, [], True)),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _build_args_namespace(
                    commands=["migrate", "info"], global_arguments=[], subcommand_args=[]
                )
            assert exc_info.value.code == 2

    def test_multi_command_args_none_creates_namespace(self):
        # Lines 127-142: args is None → creates Namespace with defaults
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors", return_value=(None, [], False)
            ),
        ):
            args, unknown = _build_args_namespace(
                commands=["migrate", "info"], global_arguments=[], subcommand_args=["--some-arg"]
            )
        assert args.command == "migrate"
        assert args.config is None
        assert args.dry_run is False
        assert args.log_format == "text"
        assert unknown == ["--some-arg"]

    def test_multi_command_extracts_db_url_from_global_args(self):
        # Lines 144-155: extract_db_arg with inline value format
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors", return_value=(None, [], False)
            ),
        ):
            args, _ = _build_args_namespace(
                commands=["migrate", "info"],
                global_arguments=["--db-url=postgresql+psycopg://localhost/db"],
                subcommand_args=[],
            )
        assert args.database_url == "postgresql+psycopg://localhost/db"

    def test_multi_command_extracts_db_url_space_separated(self):
        # Lines 152-155: space-separated format in global_arguments
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors", return_value=(None, [], False)
            ),
        ):
            args, _ = _build_args_namespace(
                commands=["migrate", "info"],
                global_arguments=["--db-url", "postgresql+psycopg://localhost/db"],
                subcommand_args=[],
            )
        assert args.database_url == "postgresql+psycopg://localhost/db"

    def test_multi_command_sets_command_from_commands(self):
        # Lines 157-158: args.command is None → set from commands[0]
        mock_parser = MagicMock()
        ns = SimpleNamespace(
            config=None,
            scripts_list=None,
            dry_run=False,
            log_dir="logs",
            log_format="text",
            log_level="info",
            log_file=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            license_key=None,
        )
        # No 'command' attribute set
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch("cli._config_helpers.parse_with_selective_errors", return_value=(ns, [], False)),
        ):
            args, _ = _build_args_namespace(
                commands=["migrate", "info"], global_arguments=[], subcommand_args=[]
            )
        assert args.command == "migrate"

    def test_multi_command_extract_db_password(self):
        # Lines 168: extract database_password
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors", return_value=(None, [], False)
            ),
        ):
            args, _ = _build_args_namespace(
                commands=["migrate", "info"],
                global_arguments=["--db-password=secret"],
                subcommand_args=[],
            )
        assert args.database_password == "secret"

    def test_multi_command_extract_license_key(self):
        # Lines 170: extract license_key
        mock_parser = MagicMock()
        with (
            patch("cli._config_helpers.create_parser", return_value=mock_parser),
            patch(
                "cli._config_helpers.parse_with_selective_errors", return_value=(None, [], False)
            ),
        ):
            args, _ = _build_args_namespace(
                commands=["migrate", "info"],
                global_arguments=["--license-key=ABC-123"],
                subcommand_args=[],
            )
        assert args.license_key == "ABC-123"


# ---------------------------------------------------------------------------
# _load_and_merge_config — uncovered branches (lines 221-229)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadAndMergeConfig:
    def _make_config(
        self,
        url="postgresql+psycopg://localhost/db",
        schema="public",
        username="user",
        password="pass",
    ):
        config = MagicMock()
        config.database.url = url
        config.database.schema = schema
        config.database.username = username
        config.database.password = password
        config.database.installed_by = None
        config.placeholders = {}
        return config

    def test_table_name_sets_history_table(self):
        # Line 221-222: args.table_name → config.history_table
        config = self._make_config()
        args = SimpleNamespace(
            config=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            table_name="my_history",
            installed_by=None,
        )
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder"),
        ):
            result = _load_and_merge_config(args, None)
        assert result.history_table == "my_history"

    def test_snapshot_table_sets_snapshot_table(self):
        config = self._make_config()
        args = SimpleNamespace(
            config=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            table_name=None,
            snapshot_table="my_snapshots",
            installed_by=None,
        )
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder"),
        ):
            result = _load_and_merge_config(args, None)
        assert result.snapshot_table == "my_snapshots"

    def test_installed_by_set_from_args(self):
        # Line 224-225: args.installed_by → config.database.installed_by
        config = self._make_config()
        args = SimpleNamespace(
            config=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            table_name=None,
            installed_by="admin",
        )
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder"),
        ):
            result = _load_and_merge_config(args, None)
        assert result.database.installed_by == "admin"

    def test_installed_by_falls_back_to_username(self):
        # Lines 226-229: no installed_by in args, but username exists → use username
        config = self._make_config()
        config.database.installed_by = None
        config.database.username = "db_user"
        args = SimpleNamespace(
            config=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            table_name=None,
            installed_by=None,
        )
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder"),
        ):
            result = _load_and_merge_config(args, None)
        assert result.database.installed_by == "db_user"

    def test_db_overrides_applied(self):
        # Lines 198-209: database overrides from args
        config = self._make_config()
        args = SimpleNamespace(
            config=None,
            database_url="postgresql+psycopg://newhost/db",
            database_username="new_user",
            database_password="new_pass",
            database_schema="new_schema",
            table_name=None,
            installed_by=None,
        )
        mock_merged_db = MagicMock()
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder") as mock_cb,
        ):
            mock_cb.merge_database_overrides.return_value = mock_merged_db
            result = _load_and_merge_config(args, None)
        mock_cb.merge_database_overrides.assert_called_once()

    def test_log_debug_called_when_log_present(self):
        # Lines 211-219: log is not None → debug calls
        config = self._make_config()
        args = SimpleNamespace(
            config=None,
            database_url=None,
            database_username=None,
            database_password=None,
            database_schema=None,
            table_name=None,
            installed_by=None,
        )
        log = MagicMock()
        with (
            patch("cli._config_helpers.load_config", return_value=config),
            patch("cli._config_helpers.ConfigBuilder"),
        ):
            _load_and_merge_config(args, log)
        assert log.debug.call_count >= 3


# ---------------------------------------------------------------------------
# _validate_db_config — uncovered branches (lines 269-327)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateDbConfig:
    def _make_parser(self):
        parser = MagicMock()
        parser.error.side_effect = SystemExit(2)
        return parser

    def test_non_migration_command_returns_early(self):
        # Line 268-269: command not in migration_commands → return
        parser = self._make_parser()
        args = SimpleNamespace(command="help")
        config = MagicMock()
        config.database = None
        _validate_db_config(args, config, parser, ["help"])
        parser.error.assert_not_called()

    def test_sqlite_no_path_calls_error(self):
        # Lines 277-288: sqlite with no path/database/url → error
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "sqlite"
        config.database.path = None
        config.database.database = None
        config.database.url = None
        config.database.schema = "main"
        with pytest.raises(SystemExit):
            _validate_db_config(args, config, parser, ["migrate"])
        parser.error.assert_called_once()

    def test_sqlite_with_path_ok(self):
        # Lines 277-290: sqlite with path → no error, schema defaults to "main"
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "sqlite"
        config.database.path = "/tmp/test.db"
        config.database.database = None
        config.database.url = None
        config.database.schema = None
        _validate_db_config(args, config, parser, ["migrate"])
        assert config.database.schema == "main"
        parser.error.assert_not_called()

    def test_sqlite_with_url_ok(self):
        # Lines 284: sqlite with url → no error
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "sqlite"
        config.database.path = None
        config.database.database = None
        config.database.url = "sqlite:////tmp/test.db"
        config.database.schema = "main"
        _validate_db_config(args, config, parser, ["migrate"])
        parser.error.assert_not_called()

    def test_cosmosdb_passes_without_error(self):
        # Line 291-292: cosmosdb → pass (no error)
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "cosmosdb"
        _validate_db_config(args, config, parser, ["migrate"])
        parser.error.assert_not_called()

    def test_no_database_config_calls_error(self):
        # Lines 293-297: no database config → error
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        # Build a config object where hasattr(config, "database") is True but config.database is falsy
        config = MagicMock()
        config.database = MagicMock()
        config.database.type = "postgresql"
        config.database.__bool__ = MagicMock(
            return_value=False
        )  # makes "if not config.database" True

        # We rely on the else branch: not hasattr or not config.database
        # Use a real object with database=None
        class FakeConfig:
            database = None

        with pytest.raises(SystemExit):
            _validate_db_config(args, FakeConfig(), parser, ["migrate"])

    def test_url_missing_calls_error(self):
        # Lines 302-305: url_provided=False and url_exists=None → error
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "postgresql"
        config.database.url = None
        config.database.host = None
        config.database.database = None
        config.database.username = "user"
        config.database.password = "pass"
        config.database.schema = "public"
        with pytest.raises(SystemExit):
            _validate_db_config(args, config, parser, ["migrate"])

    def test_mysql_missing_schema_uses_database_catalog(self):
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "mysql"
        config.database.url = "mysql+pymysql://localhost:3306/appdb"
        config.database.username = "user"
        config.database.password = "pass"
        config.database.database = "appdb"
        config.database.schema = None

        _validate_db_config(args, config, parser, ["migrate"])

        assert config.database.schema == "appdb"
        parser.error.assert_not_called()

    def test_sqlserver_missing_schema_uses_dbo(self):
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "sqlserver"
        config.database.url = "mssql+pymssql://localhost:1433/appdb"
        config.database.username = "user"
        config.database.password = "pass"
        config.database.database = "appdb"
        config.database.schema = None

        _validate_db_config(args, config, parser, ["migrate"])

        assert config.database.schema == "dbo"
        parser.error.assert_not_called()

    def test_postgresql_missing_schema_uses_public(self):
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "postgresql"
        config.database.url = "postgresql+psycopg://localhost:5432/appdb"
        config.database.username = "user"
        config.database.password = "pass"
        config.database.schema = None

        _validate_db_config(args, config, parser, ["migrate"])

        assert config.database.schema == "public"
        parser.error.assert_not_called()

    def test_postgresql_host_database_config_does_not_require_url(self):
        parser = self._make_parser()
        args = SimpleNamespace(command="migrate", database_url=None)
        config = MagicMock()
        config.database.type = "postgresql"
        config.database.url = None
        config.database.host = "localhost"
        config.database.database = "appdb"
        config.database.username = "user"
        config.database.password = "pass"
        config.database.schema = None

        _validate_db_config(args, config, parser, ["migrate"])

        assert config.database.schema == "public"
        parser.error.assert_not_called()

    def test_baseline_defaults_version_to_1(self):
        # Lines 326-327: baseline command with no baseline_version → default "1"
        parser = self._make_parser()
        args = SimpleNamespace(
            command="baseline",
            database_url="postgresql+psycopg://localhost/db",
            baseline_version=None,
        )
        config = MagicMock()
        config.database.type = "postgresql"
        config.database.url = "postgresql+psycopg://user:pass@localhost/db"
        config.database.username = "user"
        config.database.password = "pass"
        config.database.schema = "public"
        with patch("cli._config_helpers.DatabaseUrlParser") as mock_parser:
            mock_parser.parse_username.return_value = "user"
            mock_parser.parse_password.return_value = "pass"
            _validate_db_config(args, config, parser, ["baseline"])
        assert args.baseline_version == "1"


# ---------------------------------------------------------------------------
# _validate_log_format_for_cli — invalid format branch (line 240-242)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateLogFormatForCli:
    def test_invalid_format_calls_parser_error(self):
        parser = MagicMock()
        parser.error.side_effect = SystemExit(2)
        args = SimpleNamespace(log_format="xml")
        with pytest.raises(SystemExit):
            _validate_log_format_for_cli(args, parser)
        parser.error.assert_called_once()

    def test_valid_format_no_error(self):
        parser = MagicMock()
        args = SimpleNamespace(log_format="json")
        _validate_log_format_for_cli(args, parser)
        parser.error.assert_not_called()

    def test_none_format_defaults_text(self):
        parser = MagicMock()
        args = SimpleNamespace(log_format=None)
        _validate_log_format_for_cli(args, parser)
        parser.error.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_scripts_directories — uncovered branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveScriptsDirectories:
    def _make_args(
        self, scripts_list=None, config_path=None, recursive_flag=None, command="migrate"
    ):
        return SimpleNamespace(
            scripts_list=scripts_list,
            config=config_path,
            command=command,
            recursive_flag=recursive_flag,
        )

    def _make_config(self, directory="migrations", recursive=True, dir_configs=None):
        config = MagicMock()
        config.migrations.directory = directory
        config.migrations.recursive = recursive
        config.migrations.get_directory_configs.return_value = dir_configs or []
        return config

    def test_scripts_list_single_directory(self, tmp_path):
        # Lines 427-441: scripts_list with single entry
        scripts_dir = tmp_path / "migrations"
        scripts_dir.mkdir()
        args = self._make_args(scripts_list=[str(scripts_dir)])
        config = self._make_config()
        parser = MagicMock()
        parser.error.side_effect = SystemExit(2)

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert sd == scripts_dir
        assert add == []

    def test_scripts_list_multiple_directories(self, tmp_path):
        # Lines 433-439: multiple scripts dirs
        dir1 = tmp_path / "migrations"
        dir2 = tmp_path / "hotfix"
        dir1.mkdir()
        dir2.mkdir()
        args = self._make_args(scripts_list=[str(dir1), str(dir2)])
        config = self._make_config()
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert sd == dir1
        assert dir2 in add

    def test_scripts_list_additional_dir_not_found(self, tmp_path):
        # Lines 436-438: additional dir not found → parser.error
        dir1 = tmp_path / "migrations"
        dir1.mkdir()
        parser = MagicMock()
        parser.error.side_effect = SystemExit(2)
        args = self._make_args(scripts_list=[str(dir1), str(tmp_path / "nonexistent")])
        config = self._make_config()

        with pytest.raises(SystemExit):
            _resolve_scripts_directories(args, config, parser, ["migrate"])

    def test_dir_configs_multiple_dirs(self, tmp_path):
        # Lines 450-457: multiple dir_configs
        dir1 = tmp_path / "m1"
        dir2 = tmp_path / "m2"
        dir1.mkdir()
        dir2.mkdir()
        dc1 = MagicMock()
        dc1.path = str(dir1)
        dc1.recursive = True
        dc2 = MagicMock()
        dc2.path = str(dir2)
        dc2.recursive = False  # Should add to dir_recursive_map

        args = self._make_args()
        config = self._make_config(dir_configs=[dc1, dc2])
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        # dir2 should be in additional dirs and drm with recursive=False
        found_dir2 = any(str(d) == str(dir2) for d in add)
        assert found_dir2

    def test_dir_configs_first_dir_not_recursive(self, tmp_path):
        # Lines 459-460: first dir_config.recursive = False → drm entry
        dir1 = tmp_path / "m1"
        dir1.mkdir()
        dc1 = MagicMock()
        dc1.path = str(dir1)
        dc1.recursive = False

        args = self._make_args()
        config = self._make_config(dir_configs=[dc1])
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert rec is False

    def test_no_dir_configs_falls_back_to_cwd_migrations(self, tmp_path):
        # Lines 463-465: no dir_configs → default "migrations" under CWD
        args = self._make_args()
        config = self._make_config(dir_configs=[])
        parser = MagicMock()

        import os

        orig = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        finally:
            os.chdir(orig)
        # scripts_dir should be tmp_path/migrations (may or may not exist)
        assert sd is not None

    def test_cli_recursive_flag_overrides(self, tmp_path):
        # Lines 470-478: recursive_flag from CLI wins over config
        scripts_dir = tmp_path / "migrations"
        scripts_dir.mkdir()
        args = self._make_args(scripts_list=[str(scripts_dir)], recursive_flag=False)
        config = self._make_config(recursive=True)
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert rec is False
        assert drm.get(scripts_dir) is False

    def test_cli_recursive_flag_true_overrides(self, tmp_path):
        # recursive_flag=True overrides config False
        scripts_dir = tmp_path / "migrations"
        scripts_dir.mkdir()
        args = self._make_args(scripts_list=[str(scripts_dir)], recursive_flag=True)
        config = self._make_config(recursive=False)
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert rec is True

    def test_scripts_list_honors_yaml_recursive_false(self, tmp_path):
        """OBS-02: when ``--scripts`` is given without ``--recursive``, the
        top-level ``migrations.recursive: false`` from YAML must still apply.

        Pins the propagation path so a future refactor cannot silently turn
        recursive scanning back on for users who explicitly opted out.
        """
        scripts_dir = tmp_path / "migrations"
        scripts_dir.mkdir()
        args = self._make_args(scripts_list=[str(scripts_dir)], recursive_flag=None)
        config = self._make_config(recursive=False)
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert rec is False, (
            "YAML migrations.recursive=false must be honored when --scripts "
            "is given on the CLI without an explicit --recursive flag (OBS-02)."
        )

    def test_scripts_list_default_is_recursive(self, tmp_path):
        """OBS-02: documents the current default. With neither YAML nor CLI
        opting out, ``--scripts`` scans recursively. Changing this default
        would silently hide migrations for existing users — the contract is
        ``recursive: false`` to opt out.
        """
        scripts_dir = tmp_path / "migrations"
        scripts_dir.mkdir()
        args = self._make_args(scripts_list=[str(scripts_dir)], recursive_flag=None)
        # _make_config defaults recursive=True (matches MigrationsConfig default).
        config = self._make_config(recursive=True)
        parser = MagicMock()

        sd, add, rec, drm = _resolve_scripts_directories(args, config, parser, ["migrate"])
        assert rec is True


# ---------------------------------------------------------------------------
# _ensure_connection — uncovered branches (lines 529-543)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnsureConnection:
    def test_no_client_returns_early(self):
        # Lines 523-524: no client
        log = MagicMock()
        _ensure_connection(None, log, "migrate")
        log.debug.assert_not_called()

    def test_client_no_provider_returns_early(self):
        # Lines 523-524: client without provider attribute
        client = SimpleNamespace()  # no 'provider' attr
        log = MagicMock()
        _ensure_connection(client, log, "migrate")
        log.debug.assert_not_called()

    def test_already_connected_logs_debug(self):
        # Lines 530-533: is_connected() = True → connection_needed = False
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.return_value = True
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        # Should log that connection is already active
        assert any("already active" in str(c) for c in log.debug.call_args_list)

    def test_ensure_connection_called_when_needed(self):
        # Lines 536-539: connection_needed, provider has ensure_connection
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.return_value = False
        provider.ensure_connection = MagicMock()
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        provider.ensure_connection.assert_called_once()

    def test_create_connection_called_when_no_ensure(self):
        # Lines 540-542: no ensure_connection but is ConnectionProvider → create_connection
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.return_value = False
        # Remove ensure_connection
        del provider.ensure_connection
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        provider.create_connection.assert_called_once()

    def test_exception_in_is_connected_logs_debug(self):
        # Lines 534-535: is_connected raises → log.debug
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.side_effect = RuntimeError("connection error")
        provider.ensure_connection = MagicMock()
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        # Should log the exception and still try to connect
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("connection" in c.lower() for c in debug_calls)

    def test_ensure_connection_exception_logs_debug(self):
        # Lines 543-544: outer try/except → log.debug
        from db.provider_interfaces import ConnectionProvider

        provider = MagicMock(spec=ConnectionProvider)
        provider.is_connected.return_value = False
        # MagicMock(spec=ConnectionProvider) does NOT have ensure_connection by default,
        # so patch it explicitly on the instance
        provider.ensure_connection = MagicMock(side_effect=RuntimeError("conn failed"))
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("conn failed" in c or "Connection check" in c for c in debug_calls)

    def test_non_connection_provider_tries_ensure_connection(self):
        # Provider that does NOT implement ConnectionProvider
        provider = MagicMock()
        provider.ensure_connection = MagicMock()
        del provider.is_connected  # not a ConnectionProvider in terms of spec
        client = SimpleNamespace(provider=provider)
        log = MagicMock()

        _ensure_connection(client, log, "migrate")
        provider.ensure_connection.assert_called_once()


# ---------------------------------------------------------------------------
# _extract_commands_from_argv — additional branch coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractCommandsFromArgv:
    def test_db_command_stops_extraction(self):
        # Line 61-62: "db" stops further command extraction
        available = {"migrate", "db", "info"}
        global_only = {"--config", "--log-level"}
        cmds, globals_, sub = _extract_commands_from_argv(
            ["db", "check-connection", "--url", "postgresql+psycopg://localhost/db"],
            available,
            global_only,
        )
        assert "db" in cmds

    def test_expecting_value_consumed(self):
        # Lines 51-54: expecting_value_for branch
        available = {"migrate"}
        global_only = {"--config"}
        cmds, globals_, sub = _extract_commands_from_argv(
            ["migrate", "--db-url", "postgresql+psycopg://localhost/db"], available, global_only
        )
        assert "migrate" in cmds

    def test_global_arg_with_inline_value(self):
        # Lines 76-85: has_inline_value=True → no lookahead
        available = {"migrate"}
        global_only = {"--config"}
        cmds, globals_, sub = _extract_commands_from_argv(
            ["--config=dblift.yml", "migrate"], available, global_only
        )
        assert "--config=dblift.yml" in globals_
        assert "migrate" in cmds

    def test_global_arg_with_next_value(self):
        # Lines 79-83: not boolean, not inline, next arg is value
        available = {"migrate"}
        global_only = {"--config"}
        cmds, globals_, sub = _extract_commands_from_argv(
            ["--config", "dblift.yml", "migrate"], available, global_only
        )
        assert "--config" in globals_
        assert "dblift.yml" in globals_
