from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]


def test_plugin_entry_points_doc_stays_oss_only() -> None:
    text = (ROOT / "docs" / "developer-guide" / "plugin-entry-points.md").read_text(
        encoding="utf-8"
    )

    for token in ("dblift-enterprise", "dblift_pro", "dblift_enterprise"):
        assert token not in text


def test_cli_api_reference_does_not_point_at_paid_handlers() -> None:
    text = (ROOT / "docs" / "api-reference" / "cli.md").read_text(encoding="utf-8")

    for token in ("dblift_pro", "dblift_enterprise"):
        assert token not in text


def test_repo_paid_surface_guard_passes() -> None:
    guard = ROOT / "scripts" / "oss_leak_guard.py"
    if not guard.is_file():
        # scripts/oss_leak_guard.py is source-repo-only tooling and is not
        # shipped in the OSS export (mirrors tests/unit/scripts/test_oss_leak_guard.py,
        # which is fully excluded from the export for the same reason).
        pytest.skip("scripts/oss_leak_guard.py not present (not shipped in OSS export)")

    result = subprocess.run(
        [sys.executable, "scripts/oss_leak_guard.py", "."],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_core_logger_results_stays_oss_only() -> None:
    import core.logger.results as results

    for name in (
        "DiffResult",
        "ExportSchemaResult",
        "SnapshotResult",
        "PlanResult",
        "GenerateSqlFromDiffResult",
    ):
        assert not hasattr(results, name)
