"""BUG-02 regression: ``dblift db diagnose-connection`` is the native command."""

from __future__ import annotations

import argparse

import pytest

from dblift.cli.db_utils import setup_db_utils_parser


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    db_subparsers = parser.add_subparsers(dest="db_command")
    setup_db_utils_parser(db_subparsers)
    return parser


@pytest.mark.unit
class TestDiagnoseConnectionAlias:
    def test_diagnose_connection_alias_accepted(self):
        parser = _make_parser()
        args = parser.parse_args(["diagnose-connection"])
        assert args.db_command == "diagnose-connection"
