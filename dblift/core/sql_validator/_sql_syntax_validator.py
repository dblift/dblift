"""SQL-syntax validation extracted from :class:`MigrationValidator`.

The original ``_validate_sql_syntax`` method (146 l) walks every
versioned/baseline script, applies placeholders + dialect-specific
preprocessing (Oracle SQL*Plus), splits into statements via the
:class:`SqlAnalyzer`, and validates each statement.

Pulled into a dedicated module as a standalone function taking the
validator instance as its first parameter (``mv``) so it can read
``mv._replace_placeholders``, ``mv._quirks``, ``mv.sql_analyzer``,
``mv.placeholders`` and ``mv.log`` without being a bound method.
``MigrationValidator`` keeps a thin wrapper.
"""

from __future__ import annotations

import re
import warnings
from typing import TYPE_CHECKING, List

from dblift.core.constants import LOG_CONTENT_PREVIEW_LENGTH
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning

if TYPE_CHECKING:
    from dblift.core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_sql_syntax(
    mv: "MigrationValidator",
    scripts: List[Migration],
    result: "ValidationResult",
    issues: List[str],
) -> None:
    """Validate SQL syntax in *scripts*, skipping repeatable and callback migrations."""
    for script in scripts:
        if script.type not in (MigrationType.SQL, MigrationType.BASELINE):
            continue

        # Log that we're validating this script
        mv.log.debug(f"Validating SQL syntax for {script.script_name}")

        # Debug: Log original content and placeholders
        mv.log.debug(f"Original SQL content: {script.content[:LOG_CONTENT_PREVIEW_LENGTH]}...")
        mv.log.debug(f"Available placeholders: {mv.placeholders}")

        # Apply placeholder replacement before validation
        script_content = mv._replace_placeholders(script.content)
        if mv._quirks.supports_sqlplus_preprocessing:
            ctx = mv._quirks.extract_script_context(script_content)
            script_content = mv._quirks.terminate_script_directives(script_content)
            script_content = mv._quirks.apply_script_substitution(script_content, ctx)

        # Debug: Log content after replacement
        mv.log.debug(
            f"SQL content after placeholder replacement: "
            f"{script_content[:LOG_CONTENT_PREVIEW_LENGTH]}..."
        )

        # First try to split into statements to validate each one
        try:
            statements = mv.sql_analyzer.split_statements(script_content, strict_tokenizer=True)
            if mv._quirks.supports_sqlplus_preprocessing:
                statements = [
                    stmt
                    for stmt in statements
                    if not mv._quirks.is_script_directive(stmt)
                    and mv._quirks.parse_error_policy_directive(stmt) is None
                ]
            valid_statements = 0
            invalid_statements = 0

            # Validate each statement and provide detailed errors
            for i, stmt in enumerate(statements):
                stmt_valid, stmt_error = mv.sql_analyzer.validate_sql(stmt)
                if stmt_valid:
                    valid_statements += 1
                    # Analyze the statement to determine what objects it affects
                    try:
                        analysis = mv.sql_analyzer.analyze_statement(stmt)
                        objects = analysis.get("objects", [])

                        # Log details about each object that would be affected
                        for obj in objects:
                            obj_type = obj.get("object_type", "Unknown")
                            obj_name = obj.get("object_name", "unknown")
                            mv.log.debug(
                                f"Statement {i+1} will "
                                f"{analysis.get('type', 'UNKNOWN').title()} "
                                f"{obj_type} {obj_name}"
                            )
                    except Exception as e:
                        mv.log.debug(f"Failed to analyze statement {i+1}: {e}")
                else:
                    invalid_statements += 1
                    line_info = f"Statement {i+1}"
                    # Try to extract line number from error message
                    if stmt_error and "line" in stmt_error.lower():
                        line_match = re.search(r"line\s+(\d+):(\d+)", stmt_error, re.IGNORECASE)
                        if line_match:
                            line_num = int(line_match.group(1))
                            col_num = int(line_match.group(2))
                            # Count lines in previous statements to get absolute line number
                            for prev_stmt in statements[:i]:
                                line_num += prev_stmt.count("\n")
                            line_info = f"Line {line_num}, Column {col_num}"

                    error_msg = (
                        f"SQL syntax error in {script.script_name} at {line_info}: " f"{stmt_error}"
                    )
                    issues.append(error_msg)
                    result.success = False
                    if not result.error_message:
                        result.error_message = error_msg

            # Log summary of validation
            if invalid_statements == 0:
                mv.log.debug(
                    f"Successfully validated {valid_statements} statements "
                    f"in {script.script_name}"
                )
            else:
                mv.log.debug(
                    f"Found {invalid_statements} SQL syntax errors in {script.script_name}"
                )

        except Exception as split_error:
            # BUG-07 (ADR-0013 PR-3): a tokenizer / splitter failure IS
            # a validation failure — a validator that cannot parse a
            # script cannot certify its correctness. Before this fix,
            # the code fell through to ``validate_sql(script_content)``
            # and recorded a failure only if THAT returned False; on
            # tolerant dialect paths (PostgreSQL $$-quoted bodies were
            # the skill-reported trigger) the fallback silently
            # returned True and the script was counted as a pass.
            #
            # New contract: record the split failure as a validation
            # issue first. Any extra context the fallback surfaces is
            # appended but never erases the primary failure.
            split_msg = (
                f"SQL syntax error in {script.script_name}: "
                f"failed to parse script content ({split_error})"
            )
            mv.log.warning(split_msg)
            issues.append(split_msg)
            result.success = False
            if not result.error_message:
                result.error_message = split_msg

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", TokenizerWarning)
                    valid, error = mv.sql_analyzer.validate_sql(script_content)
                if not valid and error:
                    issues.append(
                        f"SQL syntax validation context for {script.script_name}: {error}"
                    )
            except Exception as fallback_error:
                # Fallback failure is already represented by the
                # primary split-failure message; log at debug for
                # diagnostic only.
                mv.log.debug(
                    f"Fallback whole-file validation also raised "
                    f"for {script.script_name}: {fallback_error}"
                )
