"""Tests for cli/main.py decomposition — extracted functions."""

import argparse
import unittest
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from cli.main import (
    _AVAILABLE_COMMANDS,
    _add_validate_sql_options,
    _collect_placeholders,
    _extract_commands_from_argv,
    _setup_export_schema_options,
    create_parser,
)

# --- Helpers ---

_GLOBAL_ONLY_ARGS = [
    "--version",
    "--log-dir",
    "--log-format",
    "--log-level",
    "--log-file",
    "--db-url",
    "--db-username",
    "--db-password",
    "--db-schema",
    "--config",
    "--scripts",
    "--dry-run",
    "--quiet",
    "-q",
    "--no-progress",
]


def _make_args(**kwargs):
    defaults = {"placeholders": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_config(placeholders=None):
    config = MagicMock()
    config.placeholders = placeholders or {}
    return config


class TestMainCliDecomposition(unittest.TestCase):

    # --- _extract_commands_from_argv ---

    def test_extract_single_command(self):
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, [])
        self.assertEqual(sub_args, [])

    def test_extract_multi_command_with_global_args(self):
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--log-level", "debug", "info", "migrate"],
            _AVAILABLE_COMMANDS,
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["info", "migrate"])
        self.assertEqual(global_args, ["--log-level", "debug"])

    def test_extract_subcommand_args_excluded_from_globals(self):
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["migrate", "--target-version", "2"],
            _AVAILABLE_COMMANDS,
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, [])
        self.assertEqual(sub_args, ["--target-version", "2"])

    def test_extract_config_before_db_subcommand(self):
        """BUG-01: `--config F db check-connection` must route --config to globals so the
        `db` parser doesn't consume F as the `db_command` positional.
        """
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--config", "/tmp/c.yaml", "db", "check-connection"],
            _AVAILABLE_COMMANDS,
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["db"])
        self.assertIn("--config", global_args)
        self.assertIn("/tmp/c.yaml", global_args)
        self.assertNotIn("/tmp/c.yaml", sub_args)

    def test_extract_dry_run_does_not_consume_following_command(self):
        """Boolean global flag --dry-run must not swallow the next token as a value,
        otherwise `dblift --dry-run migrate` loses the `migrate` command.
        """
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--dry-run", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["--dry-run"])
        self.assertNotIn("migrate", global_args)

    def test_extract_version_does_not_consume_following_token(self):
        """Boolean global flag --version must not swallow the next token as a value."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--version", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["--version"])

    def test_extract_quiet_does_not_consume_following_command(self):
        """Boolean global flag --quiet must not swallow the next token as a value."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--quiet", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["--quiet"])
        self.assertNotIn("migrate", global_args)

    def test_extract_short_q_does_not_consume_following_command(self):
        """Short alias -q must behave the same as --quiet."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["-q", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["-q"])
        self.assertNotIn("migrate", global_args)

    def test_extract_no_progress_does_not_consume_following_command(self):
        """Boolean global flag --no-progress must not swallow the next token."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--no-progress", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["--no-progress"])
        self.assertNotIn("migrate", global_args)

    def test_extract_plan_skip_validate_sql_does_not_consume_following_command(self):
        """Boolean plan flag --skip-validate-sql must not swallow chained commands."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["plan", "--skip-validate-sql", "validate"],
            [*_AVAILABLE_COMMANDS, "plan"],
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["plan", "validate"])
        self.assertEqual(sub_args, ["--skip-validate-sql"])

    def test_extract_preflight_skip_replay_does_not_consume_following_command(self):
        """Boolean preflight flag --skip-replay must not swallow chained commands."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["preflight", "--skip-replay", "validate"],
            [*_AVAILABLE_COMMANDS, "preflight"],
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["preflight", "validate"])
        self.assertEqual(sub_args, ["--skip-replay"])

    def test_extract_quiet_with_multi_command_chain(self):
        """`dblift --quiet migrate validate` must yield both commands."""
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--quiet", "migrate", "validate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate", "validate"])
        self.assertIn("--quiet", global_args)

    def test_extract_global_arg_with_inline_value_preserves_following_command(self):
        """`--config=/tmp/c.yaml migrate` must leave `migrate` as the command,
        not let the value-lookahead swallow it because the value is already
        embedded via `=`.
        """
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--config=/tmp/c.yaml", "migrate"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["migrate"])
        self.assertEqual(global_args, ["--config=/tmp/c.yaml"])
        self.assertNotIn("migrate", global_args)

    def test_extract_scripts_with_inline_value_preserves_following_command(self):
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["--scripts=/tmp/s", "info"], _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS
        )
        self.assertEqual(commands, ["info"])
        self.assertEqual(global_args, ["--scripts=/tmp/s"])

    def test_extract_subcommand_arg_with_inline_value_preserves_following_command(self):
        commands, global_args, sub_args = _extract_commands_from_argv(
            ["validate-sql", "--fail-on=error", "migrate"],
            [*_AVAILABLE_COMMANDS, "validate-sql"],
            _GLOBAL_ONLY_ARGS,
        )
        self.assertEqual(commands, ["validate-sql", "migrate"])
        self.assertEqual(sub_args, ["--fail-on=error"])

    # --- _collect_placeholders ---

    def test_collect_from_config(self):
        args = _make_args()
        config = _make_config(placeholders={"env": "prod"})
        result = _collect_placeholders(args, config)
        self.assertEqual(result["env"], "prod")

    def test_collect_from_cli_placeholders_multiple_values(self):
        args = _make_args(placeholders=["key=val", "other=two"])
        config = _make_config()
        result = _collect_placeholders(args, config)
        self.assertEqual(result["key"], "val")
        self.assertEqual(result["other"], "two")

    def test_collect_from_cli_placeholders_comma_separated_value(self):
        args = _make_args(placeholders=["key=val,other=two"])
        config = _make_config()
        result = _collect_placeholders(args, config)
        self.assertEqual(result["key"], "val")
        self.assertEqual(result["other"], "two")

    def test_collect_merges_config_and_cli(self):
        args = _make_args(placeholders=["key=cli_val"])
        config = _make_config(placeholders={"key": "config_val", "other": "kept"})
        result = _collect_placeholders(args, config)
        self.assertEqual(result["key"], "cli_val")
        self.assertEqual(result["other"], "kept")

    def test_parser_accepts_multi_value_placeholders(self):
        # nargs="+" + action="append": single flag with multiple values
        # gives a list-of-lists — [["key=val", "other=two"]]
        args = create_parser().parse_args(["migrate", "--placeholders", "key=val", "other=two"])
        self.assertEqual(args.placeholders, [["key=val", "other=two"]])
        self.assertFalse(hasattr(args, "placeholder_list"))

    def test_parser_rejects_short_placeholder_flag(self):
        with self.assertRaises(SystemExit):
            create_parser().parse_args(["migrate", "-P", "key=val"])

    # --- _setup_export_schema_options ---

    def test_export_schema_parser_has_output_arg(self):
        export_parser = argparse.ArgumentParser()
        snapshot_parser = argparse.ArgumentParser()
        _setup_export_schema_options(export_parser, snapshot_parser)
        # --output should be present
        actions = {a.dest for a in export_parser._actions}
        self.assertIn("output", actions)
        self.assertIn("output_dir", actions)

    def test_export_schema_parser_has_source_choices(self):
        export_parser = argparse.ArgumentParser()
        snapshot_parser = argparse.ArgumentParser()
        _setup_export_schema_options(export_parser, snapshot_parser)
        source_action = None
        for action in export_parser._actions:
            if action.dest == "source":
                source_action = action
                break
        self.assertIsNotNone(source_action)
        # B7-BUG-04 added ``database-stored`` as a deprecated alias for
        # ``database-model``; the parser still accepts it even though the
        # handler normalises it back to the canonical name.
        self.assertEqual(
            sorted(source_action.choices),
            sorted(["database-model", "database-stored", "file-model", "live-database"]),
        )

    # --- _add_validate_sql_options ---

    def test_validate_sql_has_format_arg(self):
        parser = argparse.ArgumentParser()
        _add_validate_sql_options(parser)
        actions = {a.dest for a in parser._actions}
        self.assertIn("format", actions)

    def test_validate_sql_has_rule_selection_args(self):
        parser = argparse.ArgumentParser()
        _add_validate_sql_options(parser)
        actions = {a.dest for a in parser._actions}
        self.assertIn("rules_file", actions)
        self.assertIn("rule_profile", actions)
        self.assertIn("rules", actions)

    def test_validate_sql_accepts_sqlite_dialect(self):
        parser = argparse.ArgumentParser()
        _add_validate_sql_options(parser)
        args = parser.parse_args(["--dialect", "sqlite"])
        self.assertEqual(args.dialect, "sqlite")

    # --- create_parser integration ---

    def test_create_parser_returns_valid_parser(self):
        parser = create_parser()
        self.assertIsInstance(parser, argparse.ArgumentParser)
        # "migrate" subcommand should exist
        found = False
        if parser._subparsers is not None:
            for action in parser._subparsers._actions:
                if hasattr(action, "choices") and isinstance(action.choices, dict):
                    if "migrate" in action.choices:
                        found = True
        self.assertTrue(found, "migrate subcommand should be present")

    # --- BUG-01: --config not overwritten by subparser defaults ---

    def test_config_flag_preserved_for_info(self):
        """BUG-01: --config set on the top-level parser must survive info subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--config", "/path/to/dblift.yaml", "info"])
        self.assertEqual(args.config, "/path/to/dblift.yaml")

    def test_config_flag_preserved_for_migrate(self):
        """BUG-01: --config set on the top-level parser must survive migrate subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--config", "/path/to/dblift.yaml", "migrate"])
        self.assertEqual(args.config, "/path/to/dblift.yaml")

    def test_config_flag_preserved_for_baseline(self):
        """BUG-01: --config must survive baseline subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(
            ["--config", "/my/config.yaml", "baseline", "--baseline-version", "1"]
        )
        self.assertEqual(args.config, "/my/config.yaml")

    # --- BUG-02: --scripts not overwritten by subparser defaults ---

    def test_scripts_flag_preserved_for_migrate(self):
        """BUG-02: --scripts set on top-level parser must survive migrate subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--scripts", "/my/migrations", "migrate"])
        self.assertEqual(args.scripts_list, ["/my/migrations"])

    def test_scripts_flag_preserved_for_info(self):
        """BUG-02: --scripts must survive info subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--scripts", "/my/migrations", "info"])
        self.assertEqual(args.scripts_list, ["/my/migrations"])

    def test_scripts_flag_preserved_for_baseline(self):
        """BUG-02: --scripts must survive baseline subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(
            ["--scripts", "/my/migrations", "baseline", "--baseline-version", "1"]
        )
        self.assertEqual(args.scripts_list, ["/my/migrations"])

    # --- BUG-06: info --format option ---

    def test_info_parser_has_format_arg(self):
        """BUG-06: info subparser must accept --format."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["info", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_info_parser_format_default_is_table(self):
        """BUG-06: info --format default should be 'table', not None."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["info"])
        self.assertEqual(args.format, "table")

    # --- --dry-run not overwritten by subparser defaults ---

    def test_dry_run_preserved_for_migrate(self):
        """--dry-run set on top-level parser must survive migrate subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--dry-run", "migrate"])
        self.assertTrue(args.dry_run)

    def test_show_sql_preserved_for_migrate(self):
        """--show-sql should be available on migrate."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["migrate", "--show-sql"])
        self.assertEqual(args.command, "migrate")
        self.assertTrue(args.show_sql)

    def test_show_sql_preserved_for_undo(self):
        """--show-sql should be available on undo."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["undo", "--show-sql"])
        self.assertEqual(args.command, "undo")
        self.assertTrue(args.show_sql)

    def test_dry_run_preserved_for_info(self):
        """--dry-run must survive info subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--dry-run", "info"])
        self.assertTrue(args.dry_run)

    def test_dry_run_preserved_for_baseline(self):
        """--dry-run must survive baseline subparser processing."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["--dry-run", "baseline", "--baseline-version", "1"])
        self.assertTrue(args.dry_run)

    def test_dry_run_default_is_false_without_flag(self):
        """--dry-run should default to False when not provided."""
        parser = create_parser(exit_on_error=False)
        args = parser.parse_args(["migrate"])
        self.assertFalse(args.dry_run)


if __name__ == "__main__":
    unittest.main()
