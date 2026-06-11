"""Public OSS package surface guards."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_PUBLIC_TERMS = re.compile(
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
PUBLIC_PATH_PREFIXES = (
    "api/",
    "cli/",
    "config/",
    "core/",
    "db/",
    "docs/",
)
PUBLIC_ROOT_FILES = {
    "Dockerfile",
    "pyproject.toml",
    "README.md",
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
PUBLIC_DOC_FILES = {"README.md"}


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
        if not (
            relative_path in PUBLIC_ROOT_FILES or relative_path.startswith(PUBLIC_PATH_PREFIXES)
        ):
            continue
        path = ROOT / relative_path
        if not path.exists():
            continue
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        content = path.read_text(encoding="utf-8")
        if FORBIDDEN_PUBLIC_TERMS.search(content):
            offenders.append(relative_path)

    assert offenders == []


def test_oss_keeps_all_first_party_database_provider_entry_points() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    for provider in EXPECTED_PROVIDER_ENTRY_POINTS:
        assert re.search(rf"^{provider}\s*=", pyproject, re.MULTILINE), provider


def test_public_docs_only_advertise_oss_cli_commands() -> None:
    offenders: list[str] = []
    for relative_path in _tracked_files():
        if not (
            relative_path in PUBLIC_DOC_FILES or relative_path.startswith(PUBLIC_DOC_PATH_PREFIXES)
        ):
            continue
        path = ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if FORBIDDEN_PUBLIC_COMMANDS.search(content):
            offenders.append(relative_path)

    assert offenders == []
