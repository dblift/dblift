"""Write-once growth guards of the corpus."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def update_versions(
    existing: Optional[Dict[str, Any]],
    measured: Dict[str, Any],
    base_ids: List[str],
    current_ids: List[str],
) -> Dict[str, Any]:
    """Merge a measurement into ``VERSIONS.json``.

    ``size_bytes`` is the size of the first complete recording and is never rewritten, so the
    growth cap cannot be reset by measuring again. ``inputs`` may only grow, and every input id
    of the first recording (``base_ids``) must still be among ``current_ids``.
    """
    existing = existing or {}
    lost = set(base_ids) - set(current_ids)
    if lost:
        raise ValueError(f"inputs are only ever added; removed: {sorted(lost)[:5]}")
    if measured["inputs"] < existing.get("inputs", 0):
        raise ValueError(f"inputs may not shrink: {measured['inputs']} < {existing['inputs']}")
    result = {**existing, **measured}
    if "size_bytes" in existing:
        result["size_bytes"] = existing["size_bytes"]
    return result
