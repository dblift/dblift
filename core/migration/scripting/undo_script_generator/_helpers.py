"""Undo Script Generator — shared helpers.

Module-level helpers for sqlglot dialect resolution used by extractors
and reversers.
"""

from typing import Optional

from db.provider_registry import ProviderRegistry


def _default_sqlglot_read_dialect() -> Optional[str]:
    """Registry-derived safe default for ``sqlglot.parse_one(read=...)``.

    When a dialect declares no sqlglot mapping (unknown/empty dialect), the
    undo generators fall back to the permissive default sqlglot grammar.
    That dialect is the single native plugin whose quirks set
    :attr:`db.base_quirks.BaseQuirks.is_default_sqlglot_read_fallback`
    (PostgreSQL today, whose ``sqlglot_dialect`` is ``"postgres"``), resolved
    from the registry — so framework code holds no hardcoded dialect literal.
    """
    for name in sorted(p.name for p in ProviderRegistry.list_plugins()):
        quirks = ProviderRegistry.get_quirks(name)
        if quirks.is_default_sqlglot_read_fallback:
            return quirks.sqlglot_dialect
    return None


def resolve_sqlglot_read_dialect(dialect: str) -> Optional[str]:
    """Return the ``read`` dialect for ``sqlglot.parse_one`` for *dialect*.

    Uses the dialect's own ``sqlglot_dialect`` quirk when present, else the
    registry-derived PostgreSQL fallback. Shared by every undo-script
    extractor/reverser so the fallback is defined in exactly one place.
    """
    return ProviderRegistry.get_quirks(dialect).sqlglot_dialect or _default_sqlglot_read_dialect()
