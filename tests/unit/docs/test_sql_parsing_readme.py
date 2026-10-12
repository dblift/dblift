"""The parsing README's "no fallback" list is the set of dialects whose parser refuses to fall back."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dblift.db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.unit]

README = Path(__file__).resolve().parents[3] / "docs" / "sql-parsing" / "README.md"
_ITEM = re.compile(r"- \*\*No fallback \(([^)]*)\)\.\*\*")


def _dialects_without_fallback() -> set[str]:
    """Registered dialects whose regex parser sets ``SPLITS_WITHOUT_FALLBACK``; the PostgreSQL-compatible
    engines share one parser and are listed as one family."""
    ProviderRegistry.discover_plugins()
    found = set()
    for plugin in ProviderRegistry.list_plugins():
        parser = ProviderRegistry.get_quirks(plugin.name).parser_class("regex")
        if getattr(parser, "SPLITS_WITHOUT_FALLBACK", False):
            found.add("postgresql" if plugin.config_dialect == "postgresql" else plugin.name)
    return found


def _dialects_named_in_readme() -> set[str]:
    match = _ITEM.search(README.read_text(encoding="utf-8"))
    assert match, "the README has no 'No fallback (...)' item"
    names = re.split(r",| and ", match.group(1))
    return {n.strip().lower().replace(" family", "").replace(" ", "") for n in names if n.strip()}


def test_readme_no_fallback_list_matches_the_parsers() -> None:
    assert _dialects_named_in_readme() == _dialects_without_fallback()
