"""Structural invariants on the CLI argparse tree.

These are property tests, not example tests: they assert rules that must hold for
*every* (sub)command, so a new subcommand or a new flag cannot re-introduce the
same family of argparse-wiring bugs (see 1.3.1 BUG-01/02, NEW-BUG-10, and the
later --dry-run regression).

The bug pattern these tests catch:

    Top-level parser defines --foo (dest=foo).
    A subparser *also* defines --foo (dest=foo, default=None).
    When the user runs `dblift --foo=X <subcmd>`, argparse parses the top-level
    first (args.foo=X) then runs the subparser, whose default resets args.foo to
    None.

The structural rule is simple: no subparser may define an argument whose `dest`
already exists on any ancestor parser, unless the action object is the same
(i.e. inherited via ``parents=[...]``).

This also verifies, behaviorally, that a parent-level value survives invocation
of every subcommand.
"""

from __future__ import annotations

import argparse
from typing import Dict, Iterable, List, Tuple

import pytest

from cli._parser_setup import create_parser

# --- helpers -----------------------------------------------------------------


def _is_subparsers_action(action: argparse.Action) -> bool:
    return isinstance(action, argparse._SubParsersAction)


def _iter_real_actions(parser: argparse.ArgumentParser) -> Iterable[argparse.Action]:
    """Yield actions that own a dest we care about, skipping help/subparsers."""
    for action in parser._actions:
        if _is_subparsers_action(action):
            continue
        if action.dest in ("help", argparse.SUPPRESS):
            continue
        yield action


def _walk(
    parser: argparse.ArgumentParser,
    ancestors: Dict[str, argparse.Action],
    path: str,
) -> Iterable[Tuple[str, argparse.ArgumentParser, Dict[str, argparse.Action]]]:
    """Yield (path, subparser, ancestor_dest_map) for every descendant parser.

    The returned ancestor_dest_map is the *effective* ancestor map at that
    subparser's level (i.e. own dests are not yet folded in).
    """
    yield path, parser, ancestors

    # Build the dests this parser owns, then recurse into its subparser actions.
    own = dict(ancestors)
    for action in _iter_real_actions(parser):
        own.setdefault(action.dest, action)

    for action in parser._actions:
        if not _is_subparsers_action(action):
            continue
        for name, sub in action.choices.items():
            sub_path = f"{path}/{name}" if path else name
            yield from _walk(sub, own, sub_path)


# --- structural invariants ---------------------------------------------------


def test_no_subparser_redefines_ancestor_dest():
    """No subparser may define an option that an ancestor parser already owns.

    Defining the same dest in a subparser makes argparse overwrite the parent
    value with the subparser's default during parsing. This is how the
    --config / --scripts / --dry-run regressions slipped in three times.
    """
    parser = create_parser()
    collisions: List[Tuple[str, str, Tuple[str, ...], str]] = []

    for path, sub, ancestors in _walk(parser, ancestors={}, path=""):
        if not ancestors:
            continue  # root has no ancestors
        for action in _iter_real_actions(sub):
            anc = ancestors.get(action.dest)
            if anc is None or anc is action:
                continue
            collisions.append(
                (
                    path,
                    action.dest,
                    tuple(action.option_strings),
                    tuple(anc.option_strings),  # type: ignore[arg-type]
                )
            )

    if collisions:
        lines = [
            f"  at {path}: subparser defines dest={dest!r} "
            f"(opts={sub_opts}); ancestor already owns it (opts={anc_opts})"
            for path, dest, sub_opts, anc_opts in collisions
        ]
        pytest.fail(
            "Subparser redefines ancestor dest — argparse will overwrite "
            "the parent value with the subparser default.\n"
            "This is the bug family behind 1.3.1 BUG-01/02, NEW-BUG-10, and "
            "the --dry-run regression. Remove the duplicate add_argument() "
            "in the subparser.\n\n" + "\n".join(lines)
        )


# --- behavioural invariants --------------------------------------------------
# Top-level flags that every subcommand must preserve. These are the options
# the user can set before the subcommand name. Each entry is
# (cli_flag, argv_value, expected_dest, expected_value).

PARENT_FLAG_CASES = [
    ("--config", "/tmp/x.yaml", "config", "/tmp/x.yaml"),
    ("--scripts", "/tmp/scripts", "scripts_list", ["/tmp/scripts"]),
    ("--db-url", "postgresql+psycopg://h/db", "database_url", "postgresql+psycopg://h/db"),
    ("--db-username", "alice", "database_username", "alice"),
    ("--db-password", "secret", "database_password", "secret"),
    ("--db-schema", "public", "database_schema", "public"),
    ("--log-level", "debug", "log_level", "debug"),
    ("--log-format", "json", "log_format", "json"),
    ("--log-dir", "/tmp/logs", "log_dir", "/tmp/logs"),
    ("--log-file", "run.log", "log_file", "run.log"),
    ("--dry-run", None, "dry_run", True),
    ("--installed-by", "alice", "installed_by", "alice"),
    # Generated from the property registry (Task 7 / Phase 5). ``--max-snapshots``
    # is int-typed, so the parsed value is the coerced int, not the argv string.
    ("--max-snapshots", "5", "max_snapshots", 5),
    # B8-BUG-01: --recursive/--no-recursive are mutually-exclusive top-level
    # flags backed by ``store_const`` → ``recursive_flag``. Each value must
    # survive through to every subcommand's namespace.
    ("--recursive", None, "recursive_flag", True),
    ("--no-recursive", None, "recursive_flag", False),
]

# Flags that are legitimately NOT subject to the parent-preservation
# property. Each must be justified — if you add one, explain why the
# flag cannot be checked by the property test.
#
# Only long-form flags (``--foo``) appear in the meta-test's present
# set, so short aliases like ``-h`` do not need listing here.
EXEMPT_FROM_PARENT_FLAG_CASES = {
    # Terminal actions — they exit before any subcommand runs, so there is
    # no "preservation across subcommand" semantics to check.
    "--version",
    "--help",
    # Console-output toggles — they are read globally inside the logging /
    # progress layer (DBLIFT_NO_PROGRESS env var, log-level adjustment in
    # _configure_logging) rather than re-injected per subcommand, so the
    # "preserved across subcommand" property does not apply.
    "--quiet",
    "--no-progress",
    "--snapshot-table",
}


def _leaf_subcommand_invocations() -> List[Tuple[str, List[str]]]:
    """Every concrete leaf subcommand, with a minimal valid argv tail.

    We only need argv tails that successfully parse; required positionals and
    required options are provided with placeholder values.
    """
    return [
        ("migrate", ["migrate"]),
        ("info", ["info"]),
        ("validate", ["validate"]),
        ("undo", ["undo"]),
        ("clean", ["clean"]),
        ("baseline", ["baseline", "--baseline-version", "1"]),
        ("repair", ["repair"]),
        ("import-flyway", ["import-flyway"]),
        ("db list-drivers", ["db", "list-drivers"]),
        ("db validate-config", ["db", "validate-config"]),
        ("db diagnose-connection", ["db", "diagnose-connection"]),
        ("db check-connection", ["db", "check-connection"]),
    ]


@pytest.mark.parametrize("subcmd_name,subcmd_argv", _leaf_subcommand_invocations())
@pytest.mark.parametrize(
    "flag,flag_value,dest,expected",
    PARENT_FLAG_CASES,
    ids=lambda v: "" if not isinstance(v, str) else v,
)
def test_parent_flag_survives_every_subcommand(
    subcmd_name: str,
    subcmd_argv: List[str],
    flag: str,
    flag_value,
    dest: str,
    expected,
):
    """Every top-level flag must remain set after the subcommand is parsed.

    This is the behavioural mirror of the structural check above: even if a
    future change introduces a same-dest duplicate in a non-obvious way (e.g.
    through a parents= chain), this test will catch it.
    """
    parser = create_parser()

    argv: List[str] = [flag] if flag_value is None else [flag, flag_value]
    argv.extend(subcmd_argv)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        pytest.fail(f"argparse rejected valid invocation {argv!r}: exit={exc.code}")

    actual = getattr(args, dest, object())
    assert actual == expected, (
        f"After parsing {argv!r}, expected args.{dest} == {expected!r} "
        f"but got {actual!r}. A subparser is overwriting the parent value."
    )


def test_import_flyway_accepts_source_table_override():
    parser = create_parser()

    args = parser.parse_args(["import-flyway", "--flyway-table", "custom_flyway_history"])

    assert args.flyway_table == "custom_flyway_history"


@pytest.mark.parametrize(
    "subcmd_argv",
    [
        ["migrate"],
        ["undo"],
        ["baseline", "--baseline-version", "1"],
    ],
)
def test_snapshot_table_option_is_not_available_for_migration_lifecycle_commands(
    subcmd_argv: List[str],
):
    parser = create_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([*subcmd_argv, "--snapshot-table", "custom_snapshots"])


@pytest.mark.parametrize(
    "subcmd_argv",
    [
        ["migrate"],
        ["undo"],
        ["baseline", "--baseline-version", "1"],
    ],
)
def test_history_table_option_is_available_where_snapshots_are_used(
    subcmd_argv: List[str],
):
    parser = create_parser()

    args = parser.parse_args([*subcmd_argv, "--table", "custom_history"])

    assert args.table_name == "custom_history"


# --- self-check: prove the linter would have caught past regressions ---------
# These tests build a deliberately-broken mini-parser and assert that the walker
# flags it. If these ever stop failing to detect, the property test above is
# silently useless.


def _build_buggy_parser() -> argparse.ArgumentParser:
    """A tiny parser that reproduces the exact shape of BUG-01/02/NEW-BUG-10."""
    p = argparse.ArgumentParser()
    p.add_argument("--config")
    subs = p.add_subparsers(dest="command")
    migrate = subs.add_parser("migrate")
    migrate.add_argument("--config")  # same dest → overwrite bug
    return p


def test_walker_detects_known_overwrite_pattern():
    buggy = _build_buggy_parser()

    collisions = []
    for path, sub, ancestors in _walk(buggy, ancestors={}, path=""):
        if not ancestors:
            continue
        for action in _iter_real_actions(sub):
            anc = ancestors.get(action.dest)
            if anc is not None and anc is not action:
                collisions.append((path, action.dest))

    assert ("migrate", "config") in collisions, (
        "The walker must flag a subparser that re-declares a parent dest — "
        "otherwise the real test above is a no-op."
    )


def test_walker_allows_parents_inheritance():
    """Actions inherited via ``parents=[...]`` are the same object; not a bug."""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--log-level")

    p = argparse.ArgumentParser(parents=[shared])
    subs = p.add_subparsers(dest="command")
    subs.add_parser("migrate", parents=[shared])

    collisions = []
    for path, sub, ancestors in _walk(p, ancestors={}, path=""):
        if not ancestors:
            continue
        for action in _iter_real_actions(sub):
            anc = ancestors.get(action.dest)
            if anc is not None and anc is not action:
                collisions.append((path, action.dest))

    assert collisions == [], f"Actions inherited via parents= must not be flagged, got {collisions}"


# --- --format choices must stay aligned with MACHINE_READABLE_FORMATS ----------
#
# Bugbot PR 162 flagged a duplication: the set of machine-readable formats was
# inlined in cli/main.py (banner suppression) and cli/_command_handlers.py
# (log-line suppression). A third copy also lived in cli/_parser_setup.py as the
# ``--format`` choices list. PR-01 hoisted all three to cli._constants. This
# test makes that invariant executable: every machine-readable format must be a
# valid ``--format`` choice, and ``console`` is the only non-machine-readable
# choice.


def _top_level_optional_flags() -> set:
    """Return the set of ``--flag`` option strings defined directly on the
    top-level parser (including those pulled in via ``parents=[...]``).

    We include only long-form flags (``--foo``) and skip short aliases so
    the coverage set is deterministic. Subparser-local flags are out of
    scope; they are covered by ``test_no_subparser_redefines_ancestor_dest``.
    """
    parser = create_parser()
    flags: set = set()
    for action in parser._actions:
        # Skip subparsers (they are not flags).
        if isinstance(action, argparse._SubParsersAction):
            continue
        for opt in action.option_strings:
            if opt.startswith("--"):
                flags.add(opt)
    return flags


def test_every_top_level_flag_is_covered_or_exempted():
    """Any top-level flag not in PARENT_FLAG_CASES must be in EXEMPT list.

    Catches the regression pattern where a new top-level flag ships without
    an accompanying test case, silently losing coverage of the BUG-01/02
    class of argparse-wiring bugs. See the historical parent-flag overwrite regressions for concrete examples.
    """
    covered = {case[0] for case in PARENT_FLAG_CASES}
    known = covered | EXEMPT_FROM_PARENT_FLAG_CASES
    present = _top_level_optional_flags()
    orphan = present - known
    assert not orphan, (
        f"New top-level flag(s) {sorted(orphan)} are not covered by "
        f"PARENT_FLAG_CASES and not listed in EXEMPT_FROM_PARENT_FLAG_CASES. "
        "Add a case (preferred) or justify the exemption explicitly."
    )


# --- --dialect choices must be derived from the plugin registry (ADR-26 E5) ---
#
# The validate-sql ``--dialect`` choices were a hardcoded six-name list. They
# now come from the plugin registry's native dialect names so that adding or
# removing a plugin updates the CLI surface automatically (no string literals).


def _registry_native_dialect_names() -> List[str]:
    from db.provider_registry import ProviderRegistry

    return sorted(
        p.name
        for p in ProviderRegistry.list_plugins()
        if ProviderRegistry.is_native_dialect(p.name)
    )


def _validate_sql_dialect_action() -> argparse.Action:
    parser = create_parser()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        sub = action.choices.get("validate-sql")
        if sub is None:
            continue
        for sub_action in sub._actions:
            if "--dialect" in sub_action.option_strings:
                return sub_action
    raise AssertionError("validate-sql --dialect action not found")


@pytest.mark.unit
class TestPlaceholderTokensMultiFlag:
    """BUG-01: multiple --placeholders flags must all survive, not last-wins."""

    def _tokens(self, raw):
        from cli._config_helpers import _placeholder_tokens

        return _placeholder_tokens(raw)

    def test_single_flag_single_token(self):
        # nargs="+" gives ["k=v"]; action="append" wraps to [["k=v"]]
        assert self._tokens([["k=v"]]) == ["k=v"]

    def test_two_flags_both_survive(self):
        # --placeholders APP_ENV=prod --placeholders APP_NAME=Test
        # → [["APP_ENV=prod"], ["APP_NAME=Test"]]
        result = self._tokens([["APP_ENV=prod"], ["APP_NAME=Test"]])
        assert "APP_ENV=prod" in result
        assert "APP_NAME=Test" in result
        assert len(result) == 2

    def test_single_flag_multiple_space_separated_tokens(self):
        # --placeholders k1=v1 k2=v2 → [["k1=v1", "k2=v2"]]
        result = self._tokens([["k1=v1", "k2=v2"]])
        assert result == ["k1=v1", "k2=v2"]

    def test_mixed_flag_and_space_separated(self):
        # --placeholders k1=v1 k2=v2 --placeholders k3=v3
        # → [["k1=v1", "k2=v2"], ["k3=v3"]]
        result = self._tokens([["k1=v1", "k2=v2"], ["k3=v3"]])
        assert set(result) == {"k1=v1", "k2=v2", "k3=v3"}

    def test_empty_returns_empty(self):
        assert self._tokens(None) == []
        assert self._tokens([]) == []
