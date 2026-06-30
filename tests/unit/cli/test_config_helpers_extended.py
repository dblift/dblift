"""Tests for cli/_config_helpers.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock


class TestPlaceholderTokens(unittest.TestCase):
    def _t(self, val):
        from cli._config_helpers import _placeholder_tokens

        return _placeholder_tokens(val)

    def test_none_returns_empty(self):
        self.assertEqual(self._t(None), [])

    def test_empty_string_returns_empty(self):
        self.assertEqual(self._t(""), [])

    def test_single_placeholder(self):
        result = self._t("key=value")
        self.assertEqual(result, ["key=value"])

    def test_comma_separated(self):
        result = self._t("a=1,b=2")
        self.assertEqual(result, ["a=1", "b=2"])

    def test_list_input(self):
        result = self._t(["a=1", "b=2"])
        self.assertEqual(result, ["a=1", "b=2"])

    def test_list_with_comma_in_element(self):
        result = self._t(["a=1,b=2"])
        self.assertEqual(result, ["a=1", "b=2"])


class TestCollectPlaceholders(unittest.TestCase):
    def _c(self, args, config):
        from cli._config_helpers import _collect_placeholders

        return _collect_placeholders(args, config)

    def test_empty_config_and_args(self):
        args = SimpleNamespace(placeholders=None)
        config = MagicMock()
        config.placeholders = None
        result = self._c(args, config)
        self.assertEqual(result, {})

    def test_config_placeholders_merged(self):
        args = SimpleNamespace(placeholders=None)
        config = MagicMock()
        config.placeholders = {"env": "prod"}
        result = self._c(args, config)
        self.assertEqual(result.get("env"), "prod")

    def test_args_placeholders_merged(self):
        args = SimpleNamespace(placeholders="schema=public")
        config = MagicMock()
        config.placeholders = None
        result = self._c(args, config)
        self.assertEqual(result.get("schema"), "public")

    def test_args_override_config(self):
        args = SimpleNamespace(placeholders="env=staging")
        config = MagicMock()
        config.placeholders = {"env": "prod"}
        result = self._c(args, config)
        self.assertEqual(result.get("env"), "staging")


class TestCloseLogs(unittest.TestCase):
    def _cl(self, log):
        from cli._config_helpers import _close_logs

        _close_logs(log)

    def test_calls_close_method(self):
        log = MagicMock()
        self._cl(log)
        log.close.assert_called_once()

    def test_closes_sub_logs(self):
        log = MagicMock(spec=["logs"])
        sub1 = MagicMock()
        sub2 = MagicMock()
        log.logs = [sub1, sub2]
        self._cl(log)
        sub1.close.assert_called_once()
        sub2.close.assert_called_once()

    def test_handles_none_gracefully(self):
        self._cl(None)  # should not raise


class TestExtractCommandsFromArgv(unittest.TestCase):
    def test_basic_extraction(self):
        from cli._config_helpers import _extract_commands_from_argv

        available = {"migrate", "info", "validate"}
        global_only = {"--config", "--url"}
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["migrate", "--dry-run"], available, global_only
        )
        self.assertIn("migrate", commands)

    def test_empty_argv(self):
        from cli._config_helpers import _extract_commands_from_argv

        commands, global_args, sub_args = _extract_commands_from_argv([], {"migrate"}, set())
        self.assertEqual(commands, [])

    def test_global_args_separated(self):
        from cli._config_helpers import _extract_commands_from_argv

        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--url", "postgresql+psycopg://localhost/db", "migrate"], {"migrate"}, {"--url"}
        )
        self.assertIn("migrate", commands)


class TestDiscoverDefaultConfig(unittest.TestCase):
    """Default config-file discovery in the cwd (2.1.1)."""

    def _run_in(self, tmp):
        import os

        from cli._config_helpers import _discover_default_config

        prev = os.getcwd()
        os.chdir(tmp)
        try:
            return _discover_default_config()
        finally:
            os.chdir(prev)

    def test_returns_none_when_no_config_present(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self._run_in(tmp))

    def test_finds_dblift_yaml(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "dblift.yaml"), "w").close()
            result = self._run_in(tmp)
            self.assertIsNotNone(result)
            self.assertEqual(os.path.basename(result), "dblift.yaml")

    def test_finds_dblift_yml(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "dblift.yml"), "w").close()
            result = self._run_in(tmp)
            self.assertIsNotNone(result)
            self.assertEqual(os.path.basename(result), "dblift.yml")

    def test_yaml_takes_precedence_over_yml(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "dblift.yaml"), "w").close()
            open(os.path.join(tmp, "dblift.yml"), "w").close()
            result = self._run_in(tmp)
            self.assertEqual(os.path.basename(result), "dblift.yaml")


if __name__ == "__main__":
    unittest.main()
