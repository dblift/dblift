"""A ``HybridParser`` bound to Db2, which the plugin no longer serves.

Db2 reads statement facts, so ``HybridParser("db2")`` refuses to construct. The parser's regex helpers are
dialect-neutral and keep their own tests; they build the instance with the facts reader switched off.
"""

from unittest.mock import patch

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.db.plugins.db2.quirks import Db2Quirks


def legacy_db2_hybrid() -> HybridParser:
    """Return a regex-only ``HybridParser`` for Db2, as the plugin served it before statement facts."""
    with patch.object(Db2Quirks, "statement_facts_class", None):
        return HybridParser("db2")
