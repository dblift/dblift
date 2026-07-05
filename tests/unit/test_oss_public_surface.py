"""OSS public surface contract (dialect providers).

This test is protected during OSS export (see scripts/export_oss_repo.py:PROTECTED_RELATIVE_PATHS)
and asserts that the OSS package surface includes *all* first-party database
dialects via the ``dblift.providers`` entry-point group.

Decision (2026-06-05 public-core split): the public package ships all
first-party dialect entry points. Export-time filtering must never drop the
provider plugins under db/plugins/*.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]


def _tracked_files() -> set[str]:
    import subprocess

    output = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return set(output.splitlines())


def test_oss_tests_do_not_name_non_oss_tiers():
    """OSS tests should describe extension seams without naming non-OSS packages."""
    forbidden = (
        "dblift" + "_pro",
        "dblift" + "_enterprise",
        "PRO" + "-tier",
        "Enterprise" + "-tier",
        "PRO" + "/Enterprise",
        "paid " + "commands",
        "paid " + "feature",
    )
    offenders: list[str] = []

    # These tests deliberately name the non-OSS packages to assert their
    # *absence* from the OSS-only surface; that's the opposite of a leak.
    exempt_names = {"test_oss_standalone.py", "test_oss_no_paid_surface.py"}

    for path in sorted((ROOT / "tests").rglob("*")):
        if (
            path == Path(__file__).resolve()
            or path.name in exempt_names
            or path.suffix not in {".py", ".txt"}
        ):
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")

    assert offenders == []


def test_oss_repo_does_not_ship_removed_tier_modules():
    """core/sql_generator ships in OSS by design (phase2: keep OSS SQL generator
    runtime, 2026-07-03) — it's the base DDL-generation engine higher tiers'
    per-dialect generators subclass (BaseSqlGenerator/BaseAlterGenerator) and
    register into (SqlGeneratorFactory/AlterGeneratorFactory); paid-tier
    implementations live outside this module, not inside it."""
    tracked = _tracked_files()
    forbidden_roots = ("core/licensing/",)
    offenders = [
        path for path in sorted(tracked) if any(path.startswith(root) for root in forbidden_roots)
    ]

    assert offenders == []


def test_oss_cli_does_not_expose_license_key_surface():
    """OSS must never carry the actual license *key* surface (``license_key`` /
    ``--license-key``) — that's paid-tier territory.

    The ``license_info`` token is different: it's the neutral banner seam
    (``core.seams.license_info``) plus its OSS-side *consumer* (cli/main.py
    calls the seam and sets ``formatter.license_info``; _formatters.py renders
    the banner only when a higher tier populated it). That consumer is inert in
    a pure OSS install (the seam returns ``None``) and holds no license logic or
    keys, so those files are exempt for the ``license_info`` token only."""
    current_test = Path(__file__).resolve().relative_to(ROOT).as_posix()
    # Files where the neutral banner seam/consumer legitimately names
    # ``license_info`` (never ``license_key``).
    license_info_ok = {
        "core/seams/license_info.py",
        "cli/main.py",
        "core/logger/_formatters.py",
        # Tests for the banner seam/consumer legitimately name license_info.
        "tests/unit/core/logger/test_license_banner.py",
        "tests/unit/cli/test_license_banner_wiring.py",
    }

    key_offenders = []
    info_offenders = []
    for path in sorted(_tracked_files()):
        if path == current_test or not path.endswith(".py"):
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        if "--license-key" in text or "license_key" in text:
            key_offenders.append(path)
        if "license_info" in text and path not in license_info_ok:
            info_offenders.append(path)
    offenders = key_offenders + info_offenders

    assert offenders == []


def test_oss_introspection_does_not_define_license_gated_capabilities():
    capability_matrix = ROOT / "core" / "introspection" / "capability_matrix.py"
    if not capability_matrix.exists():
        # The capability matrix was removed upstream; with no module there are no
        # license-gated capabilities to define, so the guard is trivially satisfied.
        return
    text = capability_matrix.read_text(encoding="utf-8")

    assert "requires_license" not in text
    assert "Enterprise only" not in text


def test_published_docs_and_templates_do_not_reference_removed_tier_surfaces():
    docs = [
        ROOT / "docs" / "user-guide" / "commands.md",
        ROOT / "docs" / "user-guide" / "getting-started.md",
        ROOT / "docs" / "index.md",
        ROOT / "docs" / "api-reference" / "core.md",
        ROOT / "core" / "logger" / "templates" / "oldreport.html",
    ]
    forbidden = (
        "--license-key",
        "DBLIFT_LICENSE_KEY",
        "license_info",
        "core.sql_generator",
        "dblift license",
        "License Activation",
        "License Management",
        "Commercial Licensing",
        "architecture/licensing",
    )
    offenders = []

    for path in docs:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")

    assert offenders == []


def test_pypi_publish_workflow_uses_trusted_publishing():
    workflow = ROOT / ".github" / "workflows" / "publish-pypi.yml"

    text = workflow.read_text(encoding="utf-8")

    assert "id-token: write" in text
    assert "pypa/gh-action-pypi-publish" in text
    assert "password:" not in text


def test_public_docs_reference_existing_workflows():
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "README.md",
        ROOT / "docs" / "index.md",
        ROOT / "pyproject.toml",
    ]
    referenced: set[str] = set()
    workflow_pattern = re.compile(r"(?:actions/workflows/|\.github/workflows/)([A-Za-z0-9_.-]+)")

    for path in docs:
        text = path.read_text(encoding="utf-8")
        referenced.update(workflow_pattern.findall(text))
        if "security.yml" in text:
            referenced.add("security.yml")
        if "complexity.yml" in text:
            referenced.add("complexity.yml")

    missing = [
        name for name in sorted(referenced) if not (ROOT / ".github" / "workflows" / name).is_file()
    ]

    assert missing == []


def test_readme_uses_existing_local_assets():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    asset_paths = re.findall(r'<img src="([^"]+)"', readme)

    missing = [path for path in asset_paths if not (ROOT / path).is_file()]

    assert missing == []


def test_readme_local_links_resolve_inside_oss_repo():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    local_links = []

    for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", readme):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        if path:
            local_links.append(target)

    missing = [target for target in local_links if not (ROOT / target.split("#", 1)[0]).exists()]

    assert missing == []


def test_readme_installation_sync_block_preserves_heading_hierarchy():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index("<!-- BEGIN: OSS README sync: python-install -->")
    end = readme.index("<!-- END: OSS README sync: python-install -->", start)
    block = readme[start:end]

    assert "\n## " not in block
    assert "Synchronous client" not in block
    assert "DBLiftClient" not in block
    assert "Django" not in block
    assert "\n## Django\n" in readme[end:]
    assert "[Django](#django)" in readme


def test_oss_dialect_surface_covers_all_first_party_providers():
    """The declared ``[project.entry-points."dblift.providers"]`` in pyproject.toml
    must be exactly the OSS_DIALECTS set.

    This guarantees:
    - pyproject.toml registers every first-party dialect.
    - Export no longer strips provider plugins (only feature surfaces).
    """
    OSS_DIALECTS = frozenset(
        {
            "sqlite",
            "postgresql",
            "mysql",
            "mariadb",
            "oracle",
            "sqlserver",
            "db2",
            "cosmosdb",
            "duckdb",
        }
    )

    pyproject_path = ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    entry_points = data["project"]["entry-points"]["dblift.providers"]
    registered = set(entry_points.keys())

    assert registered == OSS_DIALECTS, (
        f"OSS dialect surface mismatch.\n"
        f"Expected: {sorted(OSS_DIALECTS)}\n"
        f"Got:      {sorted(registered)}\n"
        "All 9 first-party providers must be listed under "
        '[project.entry-points."dblift.providers"] in pyproject.toml. '
        "The export script must preserve (never drop) db/plugins/* entries."
    )


def test_core_secrets_docs_do_not_advertise_external_provider_uris():
    """Core may expose the registry, but provider URI docs stay out of OSS."""
    secrets_init = (ROOT / "config" / "secrets" / "__init__.py").read_text(encoding="utf-8")

    for scheme in (
        "vault://",
        "aws-secrets://",
        "aws-ssm://",
        "azure-keyvault://",
        "gcp-secrets://",
    ):
        assert scheme not in secrets_init
