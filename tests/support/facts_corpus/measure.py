"""Write-once growth guards of the corpus."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def update_versions(
    existing: Optional[Dict[str, Any]],
    measured: Dict[str, Any],
    base_ids: List[str],
    current_ids: List[str],
) -> Dict[str, Any]:
    """Merge a measurement into ``VERSIONS.json``."""
    return {}
