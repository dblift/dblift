"""Conformance rows decode hex and unicode escapes (a control character is never typed into a spec)."""

from pathlib import Path

import pytest

from tests.support.splitter_spec.spec_tables import SpecFormatError, load_conformance_rows


def script_of(tmp_path: Path, cell: str) -> str:
    spec = tmp_path / "demo.md"
    spec.write_text(
        f"## 10. Conformance examples\n\n| # | Script | Statements returned |\n| --- | --- | --- |\n| 1 | `{cell}` | `x` |\n"
    )
    return load_conformance_rows(tmp_path)[0].script


@pytest.mark.parametrize(
    "cell, expected",
    [
        ("a\\x0cb", "a\x0cb"),
        ("a\\xa0b", "a\xa0b"),
        ("a\\u2028b", "a\u2028b"),
        ("a\\x0Cb", "a\x0cb"),
        ("\\\\x0c", "\\x0c"),
        ("\\unrestrict and \\x on", "\\unrestrict and \\x on"),
        ("a\\nb\\tc", "a\nb\tc"),
    ],
)
def test_escapes_decode(tmp_path, cell, expected):
    assert script_of(tmp_path, cell) == expected


@pytest.mark.parametrize("cell", ["a\\x0", "a\\x0g", "a\\u12", "a\\u202"])
def test_a_malformed_escape_is_a_build_error(tmp_path, cell):
    with pytest.raises(SpecFormatError, match="malformed"):
        script_of(tmp_path, cell)
