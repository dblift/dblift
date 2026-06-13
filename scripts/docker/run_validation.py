#!/usr/bin/env python3
"""DBLift validation entrypoint for CI containers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace")).resolve()
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", WORKSPACE / ".dblift"))
MIGRATION_ROOT = Path(os.environ.get("MIGRATION_ROOT", WORKSPACE / "migrations")).resolve()
EXAMPLES_ROOT = Path(os.environ.get("EXAMPLES_ROOT", WORKSPACE / "examples/migrations")).resolve()
RULES_FILE = Path(os.environ.get("RULES_FILE", WORKSPACE / "config/.dblift_rules.yaml"))
DIALECT = os.environ.get("DIALECT", "postgresql")
ANNOTATION_FORMAT = os.environ.get("VALIDATION_ANNOTATION_FORMAT", "github-actions")
SARIF_FILENAME = os.environ.get("SARIF_FILENAME", "validation-results.sarif")
SUMMARY_FILENAME = os.environ.get("SUMMARY_FILENAME", "validation-summary.json")


def _parse_changed_files() -> List[str]:
    raw = os.environ.get("CHANGED_FILES", "").strip()
    if raw:
        parts = [p.strip() for p in raw.replace("\n", " ").split(" ") if p.strip()]
        return parts
    raw = os.environ.get("INPUT_PATHS", "").strip()
    if raw:
        return [p.strip() for p in raw.replace("\n", " ").split(" ") if p.strip()]
    return []


def _default_targets() -> List[str]:
    defaults: List[str] = []
    migrations = sorted(MIGRATION_ROOT.rglob("*.sql")) if MIGRATION_ROOT.exists() else []
    examples = sorted(EXAMPLES_ROOT.rglob("*.sql")) if EXAMPLES_ROOT.exists() else []
    for path in migrations + examples:
        rel = path.relative_to(WORKSPACE)
        defaults.append(str(Path("/workspace") / rel))
    return defaults


def _run_validate(command: List[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=capture, check=False)


def _build_validate_command(format_name: str, targets: List[str]) -> List[str]:
    base = ["python", "-m", "cli.main", "validate-sql"]
    base.extend(targets)
    base.extend(
        [
            "--dialect",
            DIALECT,
            "--rules-file",
            str(RULES_FILE),
            "--format",
            format_name,
        ]
    )
    return base


def _extract_json(payload: str) -> Optional[str]:
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return payload[start : end + 1]


def _normalize_sarif(raw_json: str) -> Optional[Dict[Any, Any]]:
    try:
        data: Dict[Any, Any] = json.loads(raw_json)
    except json.JSONDecodeError:
        return None

    prefix = "/workspace/"
    for run in data.get("runs", []):
        for result in run.get("results", []):
            for location in result.get("locations", []):
                physical = location.get("physicalLocation") or {}
                artifact = physical.get("artifactLocation") or {}
                uri = artifact.get("uri")
                if not uri:
                    continue
                if uri.startswith(prefix):
                    rel = uri[len(prefix) :]
                else:
                    rel = uri
                artifact["uri"] = rel
                artifact["uriBaseId"] = "ROOTPATH"
    return data


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    _write_file(path, json.dumps(data, indent=2, sort_keys=True))


def main() -> int:
    targets = _parse_changed_files()
    if not targets:
        targets = _default_targets()
    if not targets:
        print("::notice::No SQL files found for validation.")
        return 0

    annotation_cmd = _build_validate_command(ANNOTATION_FORMAT, targets)
    print(f"Running annotation validation: {' '.join(annotation_cmd)}")
    annotation_proc = _run_validate(annotation_cmd, capture=False)

    sarif_cmd = _build_validate_command("sarif", targets)
    print(f"Running SARIF validation: {' '.join(sarif_cmd)}")
    sarif_proc = _run_validate(sarif_cmd, capture=True)

    if sarif_proc.stdout:
        json_blob = _extract_json(sarif_proc.stdout)
        if json_blob:
            normalized = _normalize_sarif(json_blob)
            if normalized:
                sarif_path = OUTPUT_DIR / SARIF_FILENAME
                _write_json(sarif_path, normalized)
                print(f"SARIF report written to {sarif_path}")
            else:
                print("::warning::Unable to parse SARIF JSON output.")
        else:
            print("::warning::SARIF output did not contain JSON payload.")
    if sarif_proc.stderr:
        sys.stderr.write(sarif_proc.stderr)

    errors = warnings = infos = 0
    try:
        sarif_json = normalized if "normalized" in locals() and normalized else None
        if sarif_json:
            runs = sarif_json.get("runs") or [{}]
            for result in runs[0].get("results", []):
                level = result.get("level")
                if level == "error":
                    errors += 1
                elif level == "warning":
                    warnings += 1
                else:
                    infos += 1
    except Exception:
        pass

    summary = {
        "targets": targets,
        "flattened_migrations": str(MIGRATION_ROOT),
        "rules_file": str(RULES_FILE),
        "dialect": DIALECT,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "annotation_exit_code": annotation_proc.returncode,
        "sarif_exit_code": sarif_proc.returncode,
    }
    summary_path = OUTPUT_DIR / SUMMARY_FILENAME
    _write_json(summary_path, summary)
    print(f"Validation summary written to {summary_path}")

    return annotation_proc.returncode or sarif_proc.returncode


if __name__ == "__main__":
    sys.exit(main())
