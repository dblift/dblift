"""Private operation helpers for :mod:`api.client`.

Keep large operation bodies out of ``DBLiftClient`` so the public client class
stays readable while preserving the same public methods and behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Union

from api.events import EventType
from core.logger.results import GenerateUndoScriptResult


def _heuristic_statement_count_from_sql(sql_text: str) -> int:
    """Count lines that look like standalone SQL statements (heuristic)."""
    return sum(
        1
        for line in sql_text.split("\n")
        if line.strip() and not line.strip().startswith("--") and line.strip().endswith(";")
    )


def _apply_sql_script_warning_scan(
    result: Union[Any, GenerateUndoScriptResult],
    sql_text: str,
) -> None:
    """Set manual-review flag and collect per-line warnings from generated SQL text."""
    sql_lower = sql_text.lower()
    if "warning" in sql_lower or "requires manual review" in sql_lower:
        result.requires_manual_review = True
        for line in sql_text.split("\n"):
            if "warning" in line.lower():
                warning_msg = line.strip().lstrip("--").strip()
                if warning_msg:
                    result.add_warning(warning_msg)


def generate_undo_script_operation(
    client: Any,
    *,
    migration_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
) -> GenerateUndoScriptResult:
    """Generate one undo script for ``DBLiftClient.generate_undo_script``."""
    result = GenerateUndoScriptResult()
    migration_path = Path(migration_path)
    result.migration_path = str(migration_path)
    if output_dir:
        output_dir = Path(output_dir)

    client.events.emit(
        EventType.MIGRATION_STARTED,
        {"operation": "generate_undo_script", "migration_path": str(migration_path)},
    )

    try:
        migration = _prepare_undo_generation_migration(client, migration_path)
        result = _generate_undo_script_for_migration(
            client,
            migration_path=migration_path,
            migration=migration,
            output_dir=output_dir,
            overwrite=overwrite,
        )
        client.events.emit(
            EventType.MIGRATION_COMPLETED,
            {"result": result, "operation": "generate_undo_script"},
        )
        return result
    except FileNotFoundError as e:
        _emit_undo_generation_failure(client, result, str(e))
        raise
    except (FileExistsError, ValueError) as e:
        _emit_undo_generation_failure(client, result, str(e))
        return result
    except Exception as e:
        _emit_undo_generation_failure(client, result, f"Failed to generate undo script: {str(e)}")
        raise


def generate_undo_scripts_operation(
    client: Any,
    *,
    migration_paths: Optional[List[Union[str, Path]]] = None,
    migrations_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    recursive: bool = True,
    **kwargs: Any,
) -> List[GenerateUndoScriptResult]:
    """Generate many undo scripts for ``DBLiftClient.generate_undo_scripts``."""
    results: List[GenerateUndoScriptResult] = []

    if migration_paths is None:
        migrations_dir = (
            client._get_scripts_dir() if migrations_dir is None else Path(migrations_dir)
        )
        pattern = "**/V*.sql" if recursive else "V*.sql"
        migration_paths = [f for f in migrations_dir.glob(pattern) if f.is_file()]
    else:
        migration_paths = [Path(p) for p in migration_paths]

    client.events.emit(
        EventType.MIGRATION_STARTED,
        {"operation": "generate_undo_scripts", "count": len(migration_paths)},
    )

    for migration_path in migration_paths:
        try:
            migration_path_typed = (
                Path(migration_path) if isinstance(migration_path, str) else migration_path
            )
            client.events.emit(
                EventType.MIGRATION_STARTED,
                {
                    "operation": "generate_undo_script",
                    "migration_path": str(migration_path_typed),
                },
            )
            migration = _prepare_undo_generation_migration(client, migration_path_typed)
            result = _generate_undo_script_for_migration(
                client,
                migration_path=migration_path_typed,
                migration=migration,
                output_dir=kwargs.get("output_dir"),
                overwrite=overwrite,
            )
            client.events.emit(
                EventType.MIGRATION_COMPLETED,
                {"result": result, "operation": "generate_undo_script"},
            )
            results.append(result)
        except (FileNotFoundError, FileExistsError, ValueError) as e:
            error_result = _undo_script_error_result(migration_path, str(e))
            results.append(error_result)
            client.events.emit(
                EventType.MIGRATION_FAILED,
                {"error": str(e), "operation": "generate_undo_script"},
            )
        except Exception as e:
            error_msg = f"Failed to generate undo script: {str(e)}"
            results.append(_undo_script_error_result(migration_path, error_msg))
            client.events.emit(
                EventType.MIGRATION_FAILED,
                {"error": error_msg, "operation": "generate_undo_script"},
            )

    client.events.emit(
        EventType.MIGRATION_COMPLETED,
        {
            "operation": "generate_undo_scripts",
            "results": results,
            "success_count": sum(1 for r in results if r.success),
            "failure_count": sum(1 for r in results if not r.success),
        },
    )
    return results


def _prepare_undo_generation_migration(client: Any, migration_path: Path) -> Any:
    """Validate a path once and return the parsed SQL versioned migration.

    Returns a ``core.migration.migration.Migration`` — typed as ``Any``
    here to avoid a top-level import cycle (``Migration`` transitively
    pulls in ``api`` via the executor).
    """
    from core.migration.formats import MigrationFormat
    from core.migration.migration import Migration
    from core.migration.scripting.migration_script_manager import MigrationScriptManager

    if not migration_path.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_path}")

    script_manager = MigrationScriptManager(client.logger)
    if not script_manager.is_versioned_script_name(migration_path.name):
        raise ValueError(
            f"File is not a versioned migration: {migration_path.name}. "
            "Expected a versioned migration filename (V*__description.<ext>)."
        )

    migration = Migration(script_path=migration_path, logger=client.logger)
    if not migration.version:
        raise ValueError(f"Could not extract version from: {migration_path.name}")
    if migration.format != MigrationFormat.SQL:
        raise ValueError(
            "Automatic undo script generation supports SQL migrations (V*__.sql) only. "
            f"{migration_path.name} uses format {migration.format.value}; add a hand-written "
            "U*__.sql undo script instead."
        )
    return migration


def _generate_undo_script_for_migration(
    client: Any,
    *,
    migration_path: Path,
    migration: Any,
    output_dir: Optional[Union[str, Path]],
    overwrite: bool,
) -> GenerateUndoScriptResult:
    """Generate an undo script for an already validated Migration."""
    from core.migration.scripting.undo_script_generator import UndoScriptGenerator

    result = GenerateUndoScriptResult()

    output_dir_path: Optional[Path] = None
    if output_dir and output_dir != "":
        output_dir_path = Path(output_dir) if isinstance(output_dir, str) else output_dir
    if output_dir_path is None:
        output_dir_path = migration_path.parent

    generator = UndoScriptGenerator(dialect=client.dialect, logger=client.logger)
    expected_undo_path = generator.get_undo_script_path_for_migration(
        migration,
        output_dir=output_dir_path,
    )
    file_existed_before = expected_undo_path.exists()
    # Use the pre-parsed-migration entry point so the file isn't re-parsed
    # (we already validated + constructed ``migration`` in
    # ``_prepare_undo_generation_migration``). Bugbot review on PR #382.
    undo_path = generator.generate_undo_script_for_migration(
        migration,
        output_dir=output_dir_path,
        overwrite=overwrite,
    )

    if undo_path.exists():
        content = undo_path.read_text()
        result.statements_generated = _heuristic_statement_count_from_sql(content)
        _apply_sql_script_warning_scan(result, content)

    if overwrite and file_existed_before:
        result.overwritten = True

    result.migration_path = str(migration_path)
    result.undo_script_path = str(undo_path)
    result.success = True
    result.complete()
    return result


def _emit_undo_generation_failure(
    client: Any, result: GenerateUndoScriptResult, error_msg: str
) -> None:
    result.set_error(error_msg)
    result.complete()
    client.events.emit(
        EventType.MIGRATION_FAILED,
        {"error": error_msg, "operation": "generate_undo_script"},
    )


def _undo_script_error_result(
    migration_path: Union[str, Path], error_message: str
) -> GenerateUndoScriptResult:
    result = GenerateUndoScriptResult()
    result.migration_path = str(migration_path)
    result.set_error(error_message)
    result.complete()
    return result
