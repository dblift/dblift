"""Guard: no Pro/Enterprise feature surface in the OSS package.

Fails CI if paid-tier identifiers leak back into shipping code during an export
sync. Scans first-party shipping packages only (never tests, which legitimately
reference removed names in guards/regression docstrings)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

_ROOT = Path(__file__).resolve().parents[2]
_SHIPPING_DIRS = ("api", "cli", "config", "core", "db", "integrations")

# Identifiers with zero legitimate use in OSS shipping code. Generic words with
# valid OSS meaning (e.g. ``snapshot``, ``drift``, the ``validate_sql`` parser
# method) are intentionally excluded.
_FORBIDDEN = (
    "DiffResult",
    "PlanResult",
    "ExportSchemaResult",
    "SnapshotResult",
    "GenerateSqlFromDiffResult",
    "ValidationConfig",
    "ValidateSqlConfigClient",
    "VALIDATE_SQL_FORMATS",
    "lint_placeholder_url",
    "validate-sql",
    "dblift_pro",
    "dblift_enterprise",
)


def test_no_paid_surface_in_oss_shipping_code():
    offenders: list[str] = []
    for top in _SHIPPING_DIRS:
        base = _ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for token in _FORBIDDEN:
                if token in content:
                    offenders.append(f"{path.relative_to(_ROOT)}: {token}")
    assert not offenders, "Pro/Enterprise surface leaked into OSS shipping code:\n" + "\n".join(
        sorted(offenders)
    )
