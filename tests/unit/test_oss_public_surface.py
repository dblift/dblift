"""Public OSS package surface guards."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Code may keep neutral licensing stubs (core/licensing no-op guard), the
# neutral FeatureTier metadata (core/features.py), and inert `license_info`
# plumbing, but must not advertise dblift license gates or paid tiers.
# (`requires_license` in capability_matrix.py refers to database vendor
# editions, not dblift licensing.)
FORBIDDEN_CODE_TERMS = re.compile(
    r"\bproprietary\b|" r"\bpremium\b|" r"license key|" r"dblift_license",
    re.IGNORECASE,
)
# User-facing docs stay fully clean of enterprise/licensing language. README.md
# is exempt: it is the open-core positioning surface and names the paid
# `dblift-enterprise` package and its features on purpose.
FORBIDDEN_DOC_TERMS = re.compile(
    r"\benterprise\b|"
    r"\bproprietary\b|"
    r"\bpremium\b|"
    r"license key|"
    r"dblift_license|"
    r"core\.licensing|"
    r"FeatureTier|"
    r"requires_license|"
    r"license_info",
    re.IGNORECASE,
)
PUBLIC_CODE_PATH_PREFIXES = (
    "api/",
    "cli/",
    "config/",
    "core/",
    "db/",
)
PUBLIC_ROOT_FILES = {
    "Dockerfile",
    "pyproject.toml",
    "SECURITY.md",
}
EXPECTED_PROVIDER_ENTRY_POINTS = {
    "postgresql",
    "mysql",
    "mariadb",
    "sqlite",
    "oracle",
    "sqlserver",
    "db2",
    "cosmosdb",
}
FORBIDDEN_PUBLIC_COMMANDS = re.compile(
    r"dblift\s+(?:validate-sql|plan|diff|export-schema)\b|"
    r"\bvalidate-sql\b|"
    r"\bsnapshot-model\b",
    re.IGNORECASE,
)
PUBLIC_DOC_PATH_PREFIXES = ("docs/",)
PUBLIC_DOC_FILES: set[str] = set()


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.splitlines()


def test_public_oss_files_do_not_advertise_pro_enterprise_or_license_gates() -> None:
    offenders: list[str] = []
    for relative_path in _tracked_files():
        is_code = relative_path in PUBLIC_ROOT_FILES or relative_path.startswith(
            PUBLIC_CODE_PATH_PREFIXES
        )
        is_doc = relative_path in PUBLIC_DOC_FILES or relative_path.startswith(
            PUBLIC_DOC_PATH_PREFIXES
        )
        if not (is_code or is_doc):
            continue
        if relative_path == "docs/user-guide/ci-cd.md":
            continue  # documents OSS vs enterprise boundaries (allowed)
        path = ROOT / relative_path
        if not path.exists():
            continue
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        content = path.read_text(encoding="utf-8")
        pattern = FORBIDDEN_DOC_TERMS if is_doc else FORBIDDEN_CODE_TERMS
        if pattern.search(content):
            offenders.append(relative_path)

    assert offenders == []


def test_oss_keeps_all_first_party_database_provider_entry_points() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for provider in EXPECTED_PROVIDER_ENTRY_POINTS:
        assert re.search(rf"^{provider}\s*=", pyproject, re.MULTILINE), provider


def test_oss_license_metadata_is_apache_2() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    docs_index = (ROOT / "docs/index.md").read_text(encoding="utf-8")
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)

    assert license_text.startswith("Apache License\nVersion 2.0, January 2004\n")
    assert (
        "License :: OSI Approved :: Apache Software License" in pyproject["project"]["classifiers"]
    )
    assert "License-Apache--2.0" in readme
    assert "Apache License, Version 2.0" in readme
    assert "License-Apache--2.0" in docs_index
    assert "MIT License" not in license_text
    assert "License-MIT" not in readme
    assert "License-MIT" not in docs_index


def test_public_docs_only_advertise_oss_cli_commands() -> None:
    offenders: list[str] = []
    for relative_path in _tracked_files():
        if not (
            relative_path in PUBLIC_DOC_FILES or relative_path.startswith(PUBLIC_DOC_PATH_PREFIXES)
        ):
            continue
        if relative_path == "docs/user-guide/ci-cd.md":
            continue  # documents OSS vs enterprise boundaries (allowed)
        path = ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if FORBIDDEN_PUBLIC_COMMANDS.search(content):
            offenders.append(relative_path)

    assert offenders == []
