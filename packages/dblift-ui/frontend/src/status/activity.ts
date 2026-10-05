import type { JobEvent } from "../api/types";

const ACTIVITY: Record<string, string> = {
  "info.started": "Reading migration status…",
  "info.completed": "Status read",
};

/** Words for the latest event of the running status job. */
export function describeActivity(event: string): string {
  return ACTIVITY[event] ?? "Working…";
}

const OPERATIONS: Record<string, string> = {
  "info.started": "Reading migration status…",
  "info.completed": "Status read",
  "validation.started": "Validating…",
  "validation.completed": "Validation passed",
  "validation.failed": "Validation failed",
  "migration.started": "Applying migrations…",
  "migration.completed": "Migrations applied",
  "migration.failed": "Migration stopped",
  "undo.started": "Reverting the last migration…",
  "undo.completed": "Last migration reverted",
  "undo.failed": "Undo failed",
  "repair.started": "Repairing history…",
  "repair.completed": "History repaired",
  "repair.failed": "Repair failed",
  "baseline.started": "Recording the baseline…",
  "baseline.completed": "Baseline recorded",
  "baseline.failed": "Baseline failed",
};

/** One line of the run log for an event. */
export function describeEvent(event: JobEvent): string {
  const { script, error } = event;
  // An undo runs its U… script through the same events as a migration.
  const undo = script?.startsWith("U");
  const time = event.execution_time === undefined ? "" : ` in ${event.execution_time} ms`;
  switch (event.event) {
    case "migration.script.started":
      return undo ? `Running undo script ${script}` : `Running ${script}`;
    case "migration.script.completed":
      return undo ? `Ran undo script ${script}${time}` : `Applied ${script}${time}`;
    case "migration.script.failed":
      return undo ? `Undo script ${script} failed: ${error}` : `Failed ${script}: ${error}`;
    case "undo.script.rolled_back":
      return `Reverted with ${script}`;
  }
  const words = OPERATIONS[event.event] ?? event.event;
  return error ? `${words}: ${error}` : words;
}
