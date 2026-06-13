"""Public façade for ``OutputFormatter`` (text/HTML/JSON dispatch).

This module is a façade — the actual class definition lives in
``_formatter_impl.py`` and the per-section text-diff helpers live in the
``_format_diff_*.py`` sibling modules (split in PR-H11). Public consumers
continue to import ``OutputFormatter`` from
``core.logger.formatters.formatter`` as before.
"""

from core.logger.formatters._formatter_impl import OutputFormatter

__all__ = ["OutputFormatter"]
