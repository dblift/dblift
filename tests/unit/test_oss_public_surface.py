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
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

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
            "neon",
            "supabase",
            "aurora-postgresql",
            "alloydb",
            "yugabytedb",
            "timescaledb",
            "citus",
            "cockroachdb",
            "redshift",
            "snowflake",
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
        "All 19 first-party providers must be listed under "
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


# ── Install extras contract ───────────────────────────────────────────────
#
# Two claims live in [project.optional-dependencies] and neither is checkable
# by reading a single line of it:
#
#   1. ``all`` means all. It is a convenience meta-extra users read as
#      "everything dblift can talk to", so every *engine* extra has to be
#      reachable from it. It once named seven of seventeen, which meant a
#      Snowflake user running ``pip install dblift[all]`` got no Snowflake
#      driver and no warning.
#   2. A bare ``pip install dblift`` pulls no database client library at all.
#      Plugin discovery imports every plugin package, so the plugins are
#      written to import without their driver; shipping one engine's SDK in
#      [project].dependencies made that promise false for the other 18 and
#      taxed every install with an SDK it would never use.
#
# Extras that install something which is *not* an engine's client library.
# Everything else under [project.optional-dependencies] is an engine extra and
# must be covered by ``all``. Adding a non-engine extra means adding it here —
# deliberately — rather than letting it silently widen ``all``.
NON_ENGINE_EXTRAS = frozenset(
    {
        "all",  # the meta-extra itself
        "dev",  # test / lint toolchain
        "django",  # web framework integrations
        "fastapi",
        "flask",
        "otel",  # opentelemetry-api, tracing only
    }
)


def _optional_dependencies() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def _project_dependencies() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["dependencies"]


def _extras_reachable_from(extra: str, table: dict[str, list[str]]) -> set[str]:
    """Extras named by ``extra`` through ``dblift[...]`` self-references.

    Resolved transitively, because that is how pip resolves them: nothing stops
    a future ``all`` from delegating through an intermediate meta-extra.
    """
    seen: set[str] = set()
    pending = [extra]
    while pending:
        current = pending.pop()
        for spec in table.get(current, []):
            requirement = Requirement(spec)
            if canonicalize_name(requirement.name) != canonicalize_name("dblift"):
                continue
            for named in requirement.extras:
                if named not in seen:
                    seen.add(named)
                    pending.append(named)
    return seen


def _requirement_names(specs: list[str]) -> set[str]:
    """Canonical distribution names in ``specs``, ignoring ``dblift`` self-refs."""
    names = {canonicalize_name(Requirement(spec).name) for spec in specs}
    return names - {canonicalize_name("dblift")}


def test_all_extra_covers_every_engine_extra():
    """``dblift[all]`` must reach every database-engine extra.

    The engine set is derived from the extras table itself, not from a list
    maintained alongside it, so a new engine extra that nobody remembers to add
    to ``all`` fails here instead of shipping as a silently short install.
    """
    table = _optional_dependencies()
    engine_extras = set(table) - NON_ENGINE_EXTRAS
    covered = _extras_reachable_from("all", table)

    missing = sorted(engine_extras - covered)

    assert missing == [], (
        f"pip install dblift[all] installs no driver for: {missing}.\n"
        "Every engine extra must be reachable from the 'all' meta-extra in "
        "pyproject.toml [project.optional-dependencies]. Add the extra to "
        "'all', or — if it installs no database client library — to "
        "NON_ENGINE_EXTRAS in this test."
    )


def test_all_extra_only_names_declared_engine_extras():
    """``all`` must not name a non-existent extra, nor a non-engine one.

    pip resolves an unknown extra to nothing and only warns, so a typo inside
    ``all`` degrades to "installs less than it claims" with no failure anywhere.
    """
    table = _optional_dependencies()
    named = _extras_reachable_from("all", table)

    undeclared = sorted(named - set(table))
    non_engine = sorted(named & (NON_ENGINE_EXTRAS - {"all"}))

    assert undeclared == [], (
        f"pyproject.toml 'all' extra names extras that do not exist: {undeclared}. "
        "pip only warns about these, so the install silently comes up short."
    )
    assert non_engine == [], (
        f"pyproject.toml 'all' extra pulls in non-engine extras: {non_engine}. "
        "'all' is a database-driver meta-extra; framework and tooling extras "
        "stay opt-in."
    )


def test_no_database_driver_is_a_mandatory_dependency():
    """A bare ``pip install dblift`` must pull no engine client library.

    Every plugin is written to import without its driver — that is what lets
    ``ProviderRegistry.discover_plugins()`` register all 19 dialects on a bare
    install. Promoting one engine's driver to a mandatory dependency breaks the
    symmetry silently: the install grows for everyone, and the comments in
    ``db/`` promising "no drivers by default" become false.

    ``requirements.txt`` and ``requirements-runtime.txt`` mirror
    [project].dependencies (the runtime file says so in its own header), so
    they are held to the same rule.
    """
    table = _optional_dependencies()
    engine_extras = set(table) - NON_ENGINE_EXTRAS
    driver_names: set[str] = set()
    for extra in engine_extras:
        driver_names |= _requirement_names(table[extra])

    offenders: list[str] = []

    for name in sorted(_requirement_names(_project_dependencies()) & driver_names):
        offenders.append(f"pyproject.toml [project].dependencies: {name}")

    for filename in ("requirements.txt", "requirements-runtime.txt"):
        specs: list[str] = []
        for raw_line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                specs.append(line)
        for name in sorted(_requirement_names(specs) & driver_names):
            offenders.append(f"{filename}: {name}")

    assert offenders == [], (
        "Database client libraries must ship only in their engine extra, never "
        f"as a mandatory dependency: {offenders}. Move each into the matching "
        "[project.optional-dependencies] entry and add that extra to 'all'."
    )
