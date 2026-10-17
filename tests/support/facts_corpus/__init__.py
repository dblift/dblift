"""Snapshot corpus of statement facts and frozen text extraction, one file per dialect family."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

CORPUS_DIR = Path(__file__).resolve().parent
REPO_ROOT = CORPUS_DIR.parents[2]
FAMILIES = (
    "postgresql",
    "mysql",
    "oracle",
    "sqlserver",
    "sqlite",
    "duckdb",
    "redshift",
    "snowflake",
    "db2",
)
INPUTS_FILE = CORPUS_DIR / "inputs.jsonl"
VERSIONS_FILE = CORPUS_DIR / "VERSIONS.json"


def statement_id(sql: str) -> str:
    """Return the stable short identity of a statement or input script."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def family_file(family: str) -> Path:
    """Return the JSONL file holding one family's statements."""
    return CORPUS_DIR / f"{family}.jsonl"


def read_rows(path: Path) -> List[Dict[str, Any]]:
    """Read one JSONL file; a missing file is an empty corpus."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_versions() -> Dict[str, Any]:
    """Read the recorded sqlglot versions and measured sizes."""
    return json.loads(VERSIONS_FILE.read_text(encoding="utf-8"))
