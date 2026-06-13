"""Tests for api/_client_factory.py."""

import unittest
from unittest.mock import MagicMock


class TestResolveEnumValue(unittest.TestCase):
    def _resolve(self, raw, enum_class, default):
        from api._client_factory import _resolve_enum_value

        return _resolve_enum_value(raw, enum_class, default)

    def test_none_returns_default(self):
        from core.logger import LogLevel

        result = self._resolve(None, LogLevel, LogLevel.INFO)
        self.assertEqual(result, LogLevel.INFO)

    def test_enum_instance_returned_as_is(self):
        from core.logger import LogLevel

        result = self._resolve(LogLevel.DEBUG, LogLevel, LogLevel.INFO)
        self.assertEqual(result, LogLevel.DEBUG)

    def test_string_converted(self):
        from core.logger import LogLevel

        result = self._resolve("debug", LogLevel, LogLevel.INFO)
        self.assertEqual(result, LogLevel.DEBUG)


class TestConfiguredLogDirectory(unittest.TestCase):
    def _get(self, config):
        from api._client_factory import _configured_log_directory

        return _configured_log_directory(config)

    def test_returns_flat_log_dir(self):
        config = MagicMock()
        config.log_dir = "/tmp/logs"
        config.logging = None
        result = self._get(config)
        self.assertEqual(result, "/tmp/logs")

    def test_returns_nested_directory(self):
        config = MagicMock()
        config.log_dir = None
        config.logging.directory = "/var/log/dblift"
        result = self._get(config)
        self.assertEqual(result, "/var/log/dblift")

    def test_returns_none_when_no_dir(self):
        config = MagicMock()
        config.log_dir = None
        config.logging = None
        result = self._get(config)
        self.assertIsNone(result)


class TestEffectiveLogFileFromConfig(unittest.TestCase):
    def test_returns_log_file_from_config(self):
        from api._client_factory import effective_log_file_from_config

        config = MagicMock()
        config.log_file = "/tmp/dblift.log"
        result = effective_log_file_from_config(config)
        self.assertEqual(result, "/tmp/dblift.log")

    def test_returns_string_or_none_when_no_log_file(self):
        from api._client_factory import effective_log_file_from_config

        config = MagicMock()
        config.log_file = None
        config.logging = None  # prevent MagicMock auto-attribute chaining
        result = effective_log_file_from_config(config)
        self.assertIsInstance(result, (str, type(None)))


class TestResolveClientLogfileDir(unittest.TestCase):
    def test_returns_path_when_log_file(self):
        from pathlib import Path

        from api._client_factory import resolve_client_logfile_dir

        result = resolve_client_logfile_dir(MagicMock(), "/tmp/dblift.log")
        if result:
            self.assertIsInstance(result, Path)

    def test_returns_path_or_none_when_no_log_file(self):
        from pathlib import Path

        from api._client_factory import resolve_client_logfile_dir

        result = resolve_client_logfile_dir(MagicMock(), None)
        self.assertIsInstance(result, (Path, type(None)))


class TestClientFromSqlAlchemy(unittest.TestCase):
    def test_requires_engine_or_connection(self):
        from api._client_factory import client_from_sqlalchemy
        from config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            client_from_sqlalchemy()  # neither engine nor connection
