"""Invariant: every root-only CLI flag is classified as global.

`cli.main._extract_commands_from_argv` splits argv into global vs subcommand
arguments *before* argparse runs. A flag defined only on the root parser (not on
any subparser) must be listed in `_GLOBAL_ONLY_ARGS` (or `_GLOBAL_BOOLEAN_FLAGS`),
otherwise the preprocessor relocates it after the subcommand token and the
subparser rejects it as "unrecognized arguments". This regressed when
registry-surfaced root flags (`--installed-by`, `--max-snapshots`) were added
without updating the classification list; this test fails loudly on the next
such omission.
"""

import argparse

from cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS, _extract_commands_from_argv
from cli._parser_setup import create_parser
from cli.main import _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS


def _root_only_long_flags(parser: argparse.ArgumentParser) -> set:
    root = {o for a in parser._actions for o in a.option_strings if o.startswith("--")}
    sub: set = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for sp in choices.values():
                if isinstance(sp, argparse.ArgumentParser):
                    sub.update(
                        o for a in sp._actions for o in a.option_strings if o.startswith("--")
                    )
    return root - sub - {"--help"}


def test_every_root_only_flag_is_globally_classified():
    parser = create_parser(exit_on_error=False)
    root_only = _root_only_long_flags(parser)
    classified = set(_GLOBAL_ONLY_ARGS) | set(_GLOBAL_BOOLEAN_FLAGS)
    missing = root_only - classified
    assert not missing, (
        f"root-only flags not classified as global (will break when used with a "
        f"subcommand): {sorted(missing)}"
    )


def test_installed_by_survives_subcommand_argv_split():
    argv = ["migrate", "--installed-by", "release-bot", "--db-url", "sqlite:///x.db"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), _GLOBAL_ONLY_ARGS
    )
    # flag + its value stay in the global bucket (parsed by the root parser),
    # not relocated into subcommand args where the subparser would reject them.
    assert "--installed-by" in global_args
    assert "release-bot" in global_args
    assert "--installed-by" not in sub_args


def test_max_snapshots_survives_subcommand_argv_split():
    argv = ["migrate", "--max-snapshots", "7", "--db-url", "sqlite:///x.db"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), _GLOBAL_ONLY_ARGS
    )
    assert "--max-snapshots" in global_args
    assert "7" in global_args
    assert "--max-snapshots" not in sub_args


def test_license_key_survives_subcommand_argv_split():
    # --license-key is an enterprise-registered root-only value flag. It is not
    # visible to the completeness test in a pure-OSS parser (no enterprise
    # extension installed), so it must be classified explicitly — otherwise the
    # splitter relocates it into subcommand args and the subparser rejects it.
    argv = ["export-schema", "--license-key", "JWT.TOKEN.HERE", "--source", "live-database"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), _GLOBAL_ONLY_ARGS
    )
    assert "--license-key" in global_args
    assert "JWT.TOKEN.HERE" in global_args
    assert "--license-key" not in sub_args


def test_full_parser_accepts_installed_by_after_subcommand():
    # End-to-end through the same split the real CLI uses, then argparse.
    argv = ["migrate", "--installed-by", "release-bot", "--db-url", "sqlite:///x.db"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), _GLOBAL_ONLY_ARGS
    )
    parser = create_parser(exit_on_error=False)
    ns = parser.parse_args(global_args + ["migrate"] + sub_args)
    assert ns.installed_by == "release-bot"
