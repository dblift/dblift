"""Tests for the four ``api/_client_factory.py`` helpers introduced in PR-D4.

PR-D4 extracted the heavy ``DBLiftClient.__init__`` setup into four
helpers: ``resolve_config_or_raise``, ``build_default_logger``,
``normalize_migrations_dirs``, ``apply_ctor_overrides``. The pre-existing
``test_client_factory_extended.py`` covers the older helpers
(``_resolve_enum_value``, ``_configured_log_directory``,
``effective_log_file_from_config``, ``resolve_client_logfile_dir``,
``client_from_sqlalchemy``); this file covers the four new ones.

Together they pin the contract of every helper that ``__init__`` now
delegates to, so a future refactor of the constructor cannot silently
shift behavior.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


class TestResolveConfigOrRaise(unittest.TestCase):
    def _resolve(self, provider, explicit_config):
        from api._client_factory import resolve_config_or_raise

        return resolve_config_or_raise(provider, explicit_config)

    def test_explicit_config_takes_priority_over_provider(self):
        explicit = MagicMock(name="explicit-config")
        provider = SimpleNamespace(config=MagicMock(name="provider-config"))
        result = self._resolve(provider, explicit)
        self.assertIs(result, explicit)

    def test_falls_back_to_provider_config_when_explicit_is_none(self):
        provider_cfg = MagicMock(name="provider-config")
        provider = SimpleNamespace(config=provider_cfg)
        result = self._resolve(provider, None)
        self.assertIs(result, provider_cfg)

    def test_raises_configuration_error_when_no_config_anywhere(self):
        from config.errors import ConfigurationError

        provider = SimpleNamespace(config=None)
        with self.assertRaises(ConfigurationError) as ctx:
            self._resolve(provider, None)
        self.assertIn("explicit config or a provider with config", str(ctx.exception))


class TestBuildDefaultLogger(unittest.TestCase):
    def _config(self, **kwargs):
        cfg = MagicMock(name="cfg")
        # Defaults that mimic the no-override-no-config case.
        cfg.log_format = kwargs.get("log_format")
        cfg.log_level = kwargs.get("log_level")
        cfg.log_file = kwargs.get("log_file")
        cfg.log_dir = kwargs.get("log_dir")
        cfg.logging = kwargs.get("logging")  # None or SimpleNamespace
        return cfg

    def test_returns_dbliftlogger_with_defaults(self):
        from api._client_factory import build_default_logger
        from core.logger import DbliftLogger, LogFormat, LogLevel

        cfg = self._config()
        log = build_default_logger(cfg, None, None, None)

        self.assertIsInstance(log, DbliftLogger)
        # Defaults — TEXT format and INFO level — when neither config nor ctor sets them.
        self.assertEqual(log.format, LogFormat.TEXT)
        self.assertEqual(log.level, LogLevel.INFO)

    def test_ctor_overrides_take_priority_over_config(self):
        from api._client_factory import build_default_logger
        from core.logger import LogFormat, LogLevel

        # Config says TEXT/INFO; ctor says JSON/DEBUG.
        cfg = self._config(log_format="text", log_level="info")
        log = build_default_logger(cfg, "DEBUG", "json", None)

        self.assertEqual(log.format, LogFormat.JSON)
        self.assertEqual(log.level, LogLevel.DEBUG)

    def test_falls_back_to_config_when_no_ctor_overrides(self):
        from api._client_factory import build_default_logger
        from core.logger import LogFormat, LogLevel

        cfg = self._config(log_format="json", log_level="debug")
        log = build_default_logger(cfg, None, None, None)

        self.assertEqual(log.format, LogFormat.JSON)
        self.assertEqual(log.level, LogLevel.DEBUG)


class TestNormalizeMigrationsDirs(unittest.TestCase):
    def _config(self):
        cfg = MagicMock(name="cfg")
        cfg.migrations = MagicMock(name="migrations")
        cfg.migrations.directory = None
        cfg.migrations.directories = []
        return cfg

    def test_string_path_assigned_as_primary(self):
        from api._client_factory import normalize_migrations_dirs

        cfg = self._config()
        normalize_migrations_dirs(cfg, "/tmp/migrations")
        self.assertEqual(cfg.migrations.directory, "/tmp/migrations")

    def test_pathlib_path_assigned_as_primary(self):
        from api._client_factory import normalize_migrations_dirs

        cfg = self._config()
        normalize_migrations_dirs(cfg, Path("/tmp/migrations"))
        self.assertEqual(cfg.migrations.directory, "/tmp/migrations")

    def test_single_element_list_only_sets_primary(self):
        from api._client_factory import normalize_migrations_dirs

        cfg = self._config()
        normalize_migrations_dirs(cfg, ["/tmp/a"])
        self.assertEqual(cfg.migrations.directory, "/tmp/a")
        # ``directories`` (plural) only gets set when there is more than one entry.
        self.assertEqual(cfg.migrations.directories, [])

    def test_multi_element_list_first_is_primary_rest_are_extras(self):
        from api._client_factory import normalize_migrations_dirs

        cfg = self._config()
        normalize_migrations_dirs(cfg, ["/tmp/a", "/tmp/b", "/tmp/c"])
        self.assertEqual(cfg.migrations.directory, "/tmp/a")
        self.assertEqual(cfg.migrations.directories, ["/tmp/b", "/tmp/c"])

    def test_empty_list_leaves_config_unchanged(self):
        from api._client_factory import normalize_migrations_dirs

        cfg = self._config()
        normalize_migrations_dirs(cfg, [])
        self.assertIsNone(cfg.migrations.directory)
        self.assertEqual(cfg.migrations.directories, [])

    def test_directory_config_recursive_false_not_replaced_by_global_default(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig, DirectoryConfig

        config = DbliftConfig.from_dict(
            {
                "database": {"url": "sqlite:////tmp/test.db", "schema": "main"},
                "migrations": {"recursive": True, "directory": "/tmp/other"},
            }
        )
        normalize_migrations_dirs(config, [DirectoryConfig(path="/tmp/scripts", recursive=False)])
        configs = config.migrations.get_directory_configs()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].path, "/tmp/scripts")
        self.assertFalse(configs[0].recursive)

    def test_directory_config_recursive_true_not_replaced_by_global_default(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig, DirectoryConfig

        config = DbliftConfig.from_dict(
            {
                "database": {"url": "sqlite:////tmp/test.db", "schema": "main"},
                "migrations": {"recursive": False, "directory": "/tmp/other"},
            }
        )
        normalize_migrations_dirs(config, [DirectoryConfig(path="/tmp/scripts", recursive=True)])
        configs = config.migrations.get_directory_configs()
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0].path, "/tmp/scripts")
        self.assertTrue(configs[0].recursive)

    def test_dict_with_recursive_false_is_preserved(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig

        config = DbliftConfig.from_dict(
            {
                "database": {"url": "sqlite:////tmp/test.db", "schema": "main"},
                "migrations": {"recursive": True, "directory": "/tmp/other"},
            }
        )
        normalize_migrations_dirs(config, [{"path": "/tmp/scripts", "recursive": False}])
        configs = config.migrations.get_directory_configs()
        self.assertEqual(configs[0].path, "/tmp/scripts")
        self.assertFalse(configs[0].recursive)

    def test_duck_typed_directory_recursive_is_preserved(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig

        config = DbliftConfig.from_dict(
            {
                "database": {"url": "sqlite:////tmp/test.db", "schema": "main"},
                "migrations": {"recursive": True, "directory": "/tmp/other"},
            }
        )
        normalize_migrations_dirs(config, [SimpleNamespace(path="/tmp/scripts", recursive=False)])
        configs = config.migrations.get_directory_configs()
        self.assertEqual(configs[0].path, "/tmp/scripts")
        self.assertFalse(configs[0].recursive)

    def test_mixed_directory_config_and_path_keeps_per_dir_recursive(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig, DirectoryConfig

        config = DbliftConfig.from_dict(
            {
                "database": {"url": "sqlite:////tmp/test.db", "schema": "main"},
                "migrations": {"recursive": True, "directory": "/tmp/other"},
            }
        )
        normalize_migrations_dirs(
            config,
            [DirectoryConfig(path="/tmp/a", recursive=False), "/tmp/b"],
        )
        configs = config.migrations.get_directory_configs()
        self.assertEqual([c.path for c in configs], ["/tmp/a", "/tmp/b"])
        self.assertFalse(configs[0].recursive)
        self.assertTrue(configs[1].recursive)


class TestApplyCtorOverrides(unittest.TestCase):
    def _config(self):
        # Real-ish object: setattr should work; ``hasattr`` is true for
        # log_level/log_format/log_file but false for unknown keys.
        return SimpleNamespace(log_level=None, log_format=None, log_file=None)

    def test_known_kwargs_are_applied(self):
        from api._client_factory import apply_ctor_overrides

        cfg = self._config()
        apply_ctor_overrides(cfg, {"log_level": "DEBUG"}, None, None, None)
        self.assertEqual(cfg.log_level, "DEBUG")

    def test_unknown_kwargs_are_silently_skipped(self):
        from api._client_factory import apply_ctor_overrides

        cfg = self._config()
        # ``unknown_field`` is not declared on the config — must not crash.
        apply_ctor_overrides(cfg, {"unknown_field": "value"}, None, None, None)
        self.assertFalse(hasattr(cfg, "unknown_field"))

    def test_explicit_log_overrides_take_priority(self):
        from api._client_factory import apply_ctor_overrides

        cfg = self._config()
        # kwargs say one thing, explicit overrides say another — explicit wins.
        apply_ctor_overrides(
            cfg,
            {"log_level": "INFO", "log_format": "text"},
            log_level="ERROR",
            log_format="json",
            log_file="/tmp/x.log",
        )
        self.assertEqual(cfg.log_level, "ERROR")
        self.assertEqual(cfg.log_format, "json")
        self.assertEqual(cfg.log_file, "/tmp/x.log")

    def test_none_explicit_overrides_dont_override_kwargs(self):
        from api._client_factory import apply_ctor_overrides

        cfg = self._config()
        apply_ctor_overrides(cfg, {"log_level": "DEBUG"}, None, None, None)
        # kwargs setattr applied; the None ctor-override didn't clobber.
        self.assertEqual(cfg.log_level, "DEBUG")


if __name__ == "__main__":
    unittest.main()
