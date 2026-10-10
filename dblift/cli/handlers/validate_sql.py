"""``dblift validate-sql``: check migration SQL files without connecting to a database."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dblift.api._cli_support import ProviderRegistry
from dblift.cli._output import from_args
from dblift.cli.handlers._shared import CliCommandContext, run_json_guarded
from dblift.core.logger.results import OperationResult
from dblift.core.migration.sql.lint import (
    REVIEW,
    SAFE,
    UNSAFE,
    ScriptLint,
    lint_files,
    lint_targets,
)
from dblift.core.migration.sql.script_analysis import dialect_of


def _target_files(ctx: CliCommandContext) -> List[Path]:
    if ctx.args.files:
        return [Path(name) for name in ctx.args.files]
    directories = [d for d in (ctx.scripts_dir, *ctx.additional_scripts_dirs) if d is not None]
    if not directories and ctx.client.config.migrations.directory:
        directories = [Path(ctx.client.config.migrations.directory)]
    return lint_targets(
        directories, recursive=ctx.recursive, recursive_by_dir=ctx.dir_recursive_map
    )


def _dialect(ctx: CliCommandContext) -> str:
    """``--dialect`` when given, canonicalised; otherwise the configured database type.

    The configuration keeps its own database type: only the reading of the scripts changes.
    """
    chosen = str(getattr(ctx.args, "dialect", None) or "").strip().lower()
    if chosen:
        return ProviderRegistry.canonical_dialect_name(chosen) or chosen
    return dialect_of(ctx.client.config) or ""


def _summary(scripts: List[ScriptLint]) -> Dict[str, int]:
    counts = Counter(s.verdict for s in scripts)
    return {SAFE: counts[SAFE], REVIEW: counts[REVIEW], UNSAFE: counts[UNSAFE]}


def _print(log: Any, scripts: List[ScriptLint]) -> None:
    # dedupe=False: findings on one statement repeat its snippet, and scripts
    # repeat the same finding line; the logger would drop the copies.
    for script in scripts:
        log.info(f"{script.script}: {script.verdict}", dedupe=False)
        for finding in script.findings:
            accepted = " (allowed)" if finding.allowed else ""
            log.info(
                f"  {finding.severity:<7} {finding.code}, statement {finding.statement + 1}: "
                f"{finding.message}{accepted}",
                dedupe=False,
            )
            log.info(f"          {finding.snippet}", dedupe=False)
        for error in script.errors:
            log.info(f"  not read: {error}", dedupe=False)
    summary = _summary(scripts)
    log.info(
        f"{len(scripts)} script(s): {summary[SAFE]} SAFE, {summary[REVIEW]} REVIEW, "
        f"{summary[UNSAFE]} UNSAFE"
    )


def _handle_validate_sql(ctx: CliCommandContext) -> Tuple[bool, Any]:
    machine = from_args(ctx.args).is_machine_format

    def call() -> OperationResult:
        dialect = _dialect(ctx)
        paths = _target_files(ctx)
        missing = [p for p in paths if not p.is_file()]
        # Files named with --files are applied together: one delta. A directory holds
        # scripts already applied, so each of its scripts is read alone.
        scripts = lint_files(
            [p for p in paths if p.is_file()],
            dialect,
            ctx.placeholders,
            ctx.log,
            as_delta=bool(ctx.args.files),
        )
        result = OperationResult(
            success=not missing and all(s.verdict != UNSAFE for s in scripts),
            error_message=(
                "File not found: " + ", ".join(str(p) for p in missing) if missing else None
            ),
        )
        result.data = {
            "dialect": dialect,
            "scripts": [s.to_dict() for s in scripts],
            "summary": _summary(scripts),
        }
        result.complete()
        if not machine:
            if missing:
                ctx.log.error(result.error_message)
            _print(ctx.log, scripts)
        return result

    return run_json_guarded(ctx, "VALIDATE-SQL", call, _serialize)


def _serialize(result: OperationResult) -> Dict[str, Any]:
    return {"success": result.success, "error": result.error_message, **result.data}


_handle_validate_sql._dblift_config_only_client = True  # type: ignore[attr-defined]
_handle_validate_sql._dblift_skip_secret_resolution = True  # type: ignore[attr-defined]
