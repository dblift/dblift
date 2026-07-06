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

from cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS, _extract_commands_from_argv
from cli._parser_setup import create_parser
from cli.main import _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS, _root_only_long_flags


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


def test_extension_root_value_flag_is_auto_classified_global():
    # A paid extension registers its own root-only *value* flag that the OSS
    # parser never names. The argv splitter must classify it as global from the
    # built parser — otherwise it relocates the flag past the subcommand token
    # and the subparser rejects it as "unrecognized arguments". Simulate the
    # extension flag with a synthetic root-only value option.
    ext_flag = "--synthetic-ext-token"
    parser = create_parser(exit_on_error=False)
    parser.add_argument(ext_flag, dest="synthetic_ext_token")

    # The derivation used at the real call site picks it up as root-only.
    assert ext_flag in _root_only_long_flags(parser)

    # Feeding that derived set into the splitter keeps the flag and its value in
    # the global bucket, not leaked into subcommand args.
    global_only = list(_GLOBAL_ONLY_ARGS) + sorted(
        _root_only_long_flags(parser) - set(_GLOBAL_ONLY_ARGS)
    )
    argv = ["migrate", ext_flag, "SECRET-VALUE", "--db-url", "sqlite:///x.db"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), global_only
    )
    assert ext_flag in global_args
    assert "SECRET-VALUE" in global_args
    assert ext_flag not in sub_args


def test_full_parser_accepts_installed_by_after_subcommand():
    # End-to-end through the same split the real CLI uses, then argparse.
    argv = ["migrate", "--installed-by", "release-bot", "--db-url", "sqlite:///x.db"]
    _cmds, global_args, sub_args = _extract_commands_from_argv(
        argv, list(_AVAILABLE_COMMANDS), _GLOBAL_ONLY_ARGS
    )
    parser = create_parser(exit_on_error=False)
    ns = parser.parse_args(global_args + ["migrate"] + sub_args)
    assert ns.installed_by == "release-bot"
