"""Run one migration script for ``migrate`` and ``undo``.

The two commands differ only in which callback events surround a script, which
error event a failure fires, and how a successful run is recorded. Everything
else (journal entries, script events, result bookkeeping, failure handling)
lives here so the commands cannot drift apart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Tuple

from dblift.core.constants import SECONDS_TO_MILLISECONDS
from dblift.core.logger.results import OperationResult
from dblift.core.migration.migration import Migration

from ._script_events import emit_script_event

if TYPE_CHECKING:
    from .base_command import BaseCommand


@dataclass(frozen=True)
class ScriptRunPolicy:
    """What differs between the commands that run scripts one by one."""

    before_events: Tuple[str, ...]
    after_events: Tuple[str, ...]
    error_event: str
    failure_prefix: str
    completed_events: Tuple[str, ...] = ("migration.script.completed",)


class ScriptRunner:
    """Executes a single script: callbacks, journal, events and failure handling."""

    def __init__(self, command: "BaseCommand", policy: ScriptRunPolicy) -> None:
        """Bind the command whose collaborators run scripts and the policy that shapes the run."""
        self._command = command
        self._policy = policy

    def run(
        self,
        script: Migration,
        result: OperationResult,
        *,
        event_data: Dict[str, Any],
        on_success: Callable[[int], None],
    ) -> bool:
        """Run ``script``; return True on success, False once the failure is on ``result``.

        ``on_success`` receives the execution time in milliseconds, which includes
        the before-each callbacks.
        """
        command = self._command
        policy = self._policy
        journal = command.journal
        # Bound before any fallible call: the failure path below reads it.
        start_time = time.time()
        journal_started = False
        started_emitted = False
        # Each started event gets exactly one terminal event, and the error
        # event fires at most once per run.
        terminal_emitted = False
        error_event_fired = False

        try:
            for event in policy.before_events:
                command._fire(event)

            if journal:
                journal.start_migration(
                    script.script_name,
                    details={
                        "version": script.version,
                        "description": script.description,
                        "type": script.type.value if script.type else "SQL",
                    },
                )
                journal_started = True

            emit_script_event("migration.script.started", event_data)
            started_emitted = True

            command.execution_engine.execute_migration(script, result)
            execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

            if result.error_message:
                # ExecutionEngine already set the error, recorded the failed
                # migration in history and rolled back its own transaction.
                if journal:
                    journal.end_migration(
                        script.script_name,
                        success=False,
                        error_message=result.error_message,
                        execution_time=execution_time,
                    )
                    journal_started = False
                emit_script_event(
                    "migration.script.failed",
                    {
                        **event_data,
                        "error": result.error_message,
                        "execution_time": execution_time,
                    },
                )
                terminal_emitted = True
                error_event_fired = True
                command._fire(policy.error_event)
                return False

            if journal:
                journal.end_migration(
                    script.script_name, success=True, execution_time=execution_time
                )
                journal_started = False

            on_success(execution_time)

            for event in policy.completed_events:
                emit_script_event(event, {**event_data, "execution_time": execution_time})
            terminal_emitted = True

            for event in policy.after_events:
                command._fire(event)
            return True

        except Exception as e:
            if error_event_fired:
                # The failure was already reported in full; this is the error
                # callback itself failing.
                raise
            error = result.error_message or str(e)
            if not result.error_message:
                command.log.error(f"{policy.failure_prefix} for {script.script_name}: {e}")
                result.set_error(f"{policy.failure_prefix}: {e}")

            execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)
            if journal and journal_started:
                journal.end_migration(
                    script.script_name,
                    success=False,
                    error_message=error,
                    execution_time=execution_time,
                )
            if started_emitted and not terminal_emitted:
                emit_script_event(
                    "migration.script.failed",
                    {**event_data, "error": error, "execution_time": execution_time},
                )
            command._fire(policy.error_event)
            return False
