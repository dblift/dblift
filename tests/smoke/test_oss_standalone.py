"""OSS standalone smoke probes for module discoverability and CLI tier leaks."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OSS_ROOTS = ("api", "cli", "config", "core", "db", "integrations")


def test_oss_roots_discoverable_without_higher_tier_packages(tmp_path):
    oss_source = tmp_path / "oss_source"
    oss_source.mkdir()
    for root in OSS_ROOTS:
        source_root = ROOT / root
        assert source_root.exists(), f"Missing OSS source root: {source_root}"
        (oss_source / root).symlink_to(source_root, target_is_directory=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(oss_source)
    roots = repr(OSS_ROOTS)

    probe = f"""
import importlib.util

missing = []
# find_spec checks OSS-only import-path discoverability without executing package code.
for mod in {roots}:
    if importlib.util.find_spec(mod) is None:
        missing.append(mod)

leaks = []
for mod in ("dblift_pro", "dblift_enterprise"):
    spec = importlib.util.find_spec(mod)
    if spec is not None:
        leaks.append(f"{{mod}}: {{spec.origin}}")

if missing:
    raise SystemExit("OSS modules not importable: " + ", ".join(missing))
if leaks:
    raise SystemExit("higher-tier modules importable: " + ", ".join(leaks))
"""
    out = subprocess.run(
        [sys.executable, "-S", "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stderr or out.stdout


def _oss_builtin_command_choices(monkeypatch):
    """Subparser choices map (name -> parser) for a pure-OSS install.

    Entry points are patched empty so this reflects OSS builtins only: the
    lifecycle commands plus the premium-command stubs registered natively by
    ``_register_premium_stub_parsers``.
    """
    from cli import extensions
    from cli._parser_setup import create_parser

    monkeypatch.setattr(extensions.metadata, "entry_points", lambda group: [])
    parser = create_parser()
    subparser = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return subparser.choices


def _assert_present_only_as_stub(choices, word):
    """A paid command may appear in OSS, but only as a no-op advertising stub.

    The anti-leak contract is now "no paid *implementation* in OSS", not "no
    paid command *name*": since 2026-07 the OSS CLI advertises paid commands as
    labeled stubs (see ``cli/premium_manifest.py``). A stub carries zero option
    flags; a real relocated parser would expose its flags, so this still catches
    an accidental leak of a functional paid command into OSS builtins.
    """
    assert word in choices, f"premium command '{word}' should appear as an OSS stub"
    stub = choices[word]
    leaked_flags = [s for action in stub._actions for s in action.option_strings]
    assert leaked_flags == [], (
        f"paid command '{word}' exposes option flags {leaked_flags} in the OSS CLI — "
        f"it must appear only as a no-op stub, not a real implementation"
    )


def test_oss_builtin_cli_exposes_relocated_paid_commands_only_as_stubs(monkeypatch):
    choices = _oss_builtin_command_choices(monkeypatch)

    for word in ("diff", "export-schema", "snapshot"):
        _assert_present_only_as_stub(choices, word)


def test_oss_builtin_cli_exposes_remaining_paid_commands_only_as_stubs(monkeypatch):
    choices = _oss_builtin_command_choices(monkeypatch)

    for word in ("validate-sql", "plan", "preflight"):
        _assert_present_only_as_stub(choices, word)
