"""Direct tests for ``_add_registry_flags``: the bool/float/str branches only fire
for a registry property that has no explicit flag and no legacy alias yet — none
of the current PROPERTY_REGISTRY entries satisfy that (they're all wired
explicitly), so these branches need synthetic specs to exercise at all.
"""

from __future__ import annotations

import argparse

from cli._parser_setup import _add_registry_flags
from config.property_registry import PropertySpec


def test_add_registry_flags_covers_bool_float_and_default_str_types(monkeypatch):
    synthetic_registry = [
        PropertySpec("new_bool_flag", "bool", False, help="synthetic bool"),
        PropertySpec("new_float_flag", "float", 1.0, help="synthetic float"),
        PropertySpec("new_str_flag", "str", "x", help="synthetic str"),
    ]
    monkeypatch.setattr("config.property_registry.PROPERTY_REGISTRY", synthetic_registry)

    parser = argparse.ArgumentParser(add_help=False)
    _add_registry_flags(parser)

    args = parser.parse_args(
        ["--new-bool-flag", "--new-float-flag", "2.5", "--new-str-flag", "hello"]
    )

    assert args.new_bool_flag is True
    assert args.new_float_flag == 2.5
    assert args.new_str_flag == "hello"
