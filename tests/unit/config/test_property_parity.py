"""Parity invariant: every registry property is reachable on every surface.

If a NON-xfail case here fails, a property was added to
config/property_registry.py but not wired into one of: the CLI parser,
from_env_dict, or from_dict/merge.

_PENDING_CLI / _PENDING_ENV list properties whose surface is not wired YET
(cleared incrementally by Phases 2-5 of
docs/superpowers/plans/2026-07-01-config-surface-parity.md). They are marked
strict-xfail: when a later phase wires the surface the case starts passing,
strict-xfail turns that into a failure, and the name MUST be deleted from the
pending set. That is the signal the migration progressed.
"""

import argparse

import pytest

from cli._parser_setup import create_parser
from config.dblift_config import DbliftConfig
from config.property_registry import PROPERTY_REGISTRY, PropertySpec

# Runtime-only meta flags: intentionally NOT persistent properties (absent from
# PROPERTY_REGISTRY). Declared here so this test can assert they are never read
# from a DBLIFT_* environment variable — i.e. that they are CLI-only by design.
CLI_ONLY_FLAGS = [
    PropertySpec("version", "bool", False, cli_only=True),
    PropertySpec("quiet", "bool", False, cli_only=True),
    PropertySpec("no_progress", "bool", False, cli_only=True),
    PropertySpec("config", "str", None, cli_only=True),
]

# Populated empirically (see module history). Names are spec.name.
_PENDING_CLI: set = set()
_PENDING_ENV: set = set()


def _all_option_strings(parser: argparse.ArgumentParser) -> set:
    seen: set = set()

    def walk(p: argparse.ArgumentParser) -> None:
        for action in p._actions:
            for opt in action.option_strings:
                seen.add(opt)
            choices = getattr(action, "choices", None)
            if isinstance(choices, dict):
                for sub in choices.values():
                    if isinstance(sub, argparse.ArgumentParser):
                        walk(sub)

    walk(parser)
    return seen


def _sample_value(spec) -> str:
    return {"int": "5", "float": "1.5", "bool": "true"}.get(spec.type, "x")


def _present(data: dict, dotted: str) -> bool:
    if "." in dotted:
        head, tail = dotted.split(".", 1)
        return isinstance(data.get(head), dict) and tail in data[head]
    return dotted in data


def _cli_param(spec):
    marks = (
        [pytest.mark.xfail(strict=True, reason="CLI flag pending later phase")]
        if spec.name in _PENDING_CLI
        else []
    )
    return pytest.param(spec, marks=marks, id=spec.name)


def _env_param(spec):
    marks = (
        [pytest.mark.xfail(strict=True, reason="env read pending later phase")]
        if spec.name in _PENDING_ENV
        else []
    )
    return pytest.param(spec, marks=marks, id=spec.name)


# Properties whose CLI flag is registered only by the Pro/Enterprise
# cli_extensions (see cli/_parser_setup.py::_add_registry_flags deferred_specs).
# In an OSS-only install (no Pro extension) the flag genuinely does not exist on
# the parser; this is by design, not a coverage gap. The monorepo (Pro present)
# still asserts full coverage for these — only a genuinely-absent flag skips.
_PRO_DEFERRED_CLI = {"max_snapshots", "snapshot_table"}


@pytest.mark.parametrize(
    "spec",
    [_cli_param(s) for s in PROPERTY_REGISTRY if not s.cli_exempt and not s.cli_only],
)
def test_cli_flag_exists(spec):
    flags = _all_option_strings(create_parser(exit_on_error=False))
    present = spec.cli in flags or any(a in flags for a in spec.cli_aliases)
    if not present and spec.name in _PRO_DEFERRED_CLI:
        pytest.skip(
            f"{spec.name}: CLI flag registered only by the Pro extension, absent in this install"
        )
    assert present, f"{spec.name}: no CLI flag ({spec.cli} or aliases {spec.cli_aliases})"


@pytest.mark.parametrize("spec", [_env_param(s) for s in PROPERTY_REGISTRY])
def test_env_var_recognised(spec, monkeypatch):
    monkeypatch.setenv(spec.env, _sample_value(spec))
    env_dict = DbliftConfig.from_env_dict()
    assert _present(env_dict, spec.name), f"{spec.name}: {spec.env} not read by from_env_dict"


@pytest.mark.parametrize("spec", CLI_ONLY_FLAGS, ids=lambda s: s.name)
def test_cli_only_flags_have_no_env(spec, monkeypatch):
    monkeypatch.setenv(spec.env, "x")
    env_dict = DbliftConfig.from_env_dict()
    assert not _present(
        env_dict, spec.name
    ), f"{spec.name} is cli_only but from_env_dict read {spec.env}"
