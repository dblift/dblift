import type { JobEvent } from "../api/types";

/**
 * What a run's events say about each script, so the rail can move before the
 * final status arrives. Keys are migration file names.
 */
export function liveStates(events: JobEvent[]): Record<string, string> {
  const states: Record<string, string> = {};
  for (const { event, script } of events) {
    // An undo runs its U… script through the same events as a migration: those say
    // nothing about the migration itself, which only its rollback (below) changes.
    if (!script || (script.startsWith("U") && event.startsWith("migration.script."))) {
      continue;
    }
    if (event === "migration.script.started") {
      states[script] = "RUNNING";
    } else if (event === "migration.script.completed") {
      states[script] = "SUCCESS";
    } else if (event === "migration.script.failed") {
      states[script] = "FAILED";
    } else if (event === "undo.script.rolled_back") {
      // The event names the undo script (U…); its migration (V…) is pending again.
      states[`V${script.slice(1)}`] = "PENDING";
    }
  }
  return states;
}
