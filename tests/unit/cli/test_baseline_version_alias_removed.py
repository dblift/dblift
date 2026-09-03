"""Regression test: ``baseline`` parser no longer carries a dead ``--version`` alias.

Cursor bot found: ``_add_baseline_options`` registered ``--version`` as an alias
for ``--baseline-version``. But ``cli/main.py`` classifies ``--version`` as a
global-only arg and intercepts it before subparsers see it — the top-level
``--version`` flag prints the tool version and exits.

So ``dblift baseline --version 1.0.0`` printed the dblift version instead of
baselining. The alias was silently dead. The fix removes it.
"""

from __future__ import annotations

import argparse

import pytest

from dblift.cli._parser_setup import _add_baseline_options


def _make_baseline_parser():
    parser = argparse.ArgumentParser()
    _add_baseline_options(parser)
    return parser


@pytest.mark.unit
class TestBaselineVersionAliasRemoved:
    def test_baseline_version_flag_still_works(self):
        """The canonical ``--baseline-version`` flag is still recognized."""
        parser = _make_baseline_parser()
        ns = parser.parse_args(["--baseline-version", "1.2.3"])
        assert ns.baseline_version == "1.2.3"

    def test_version_alias_is_not_registered(self):
        """``--version`` must NOT be an alias — it's owned by the top-level parser."""
        parser = _make_baseline_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--version", "1.2.3"])
