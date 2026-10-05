import type { Migration } from "../api/types";

export type Tone = "ok" | "warn" | "error" | "info" | "muted";

interface StateInfo {
  label: string;
  tone: Tone;
  hint: string;
}

// Keyed by the state string the engine reports. Only the first four have been
// observed; the others are best guesses, and anything unlisted is shown as is.
const STATES: Record<string, StateInfo> = {
  SUCCESS: { label: "Applied", tone: "ok", hint: "Ran successfully on this database." },
  PENDING: { label: "Pending", tone: "warn", hint: "Not yet run on this database." },
  FAILED: { label: "Failed", tone: "error", hint: "Stopped with an error. Repair before migrating again." },
  UNDONE: { label: "Undone", tone: "muted", hint: "Was applied, then reverted by its undo script." },
  MISSING: { label: "Missing", tone: "error", hint: "Recorded in the database, but its file is not in this folder." },
  OUT_OF_ORDER: { label: "Out of order", tone: "warn", hint: "Applied after a later version." },
  FUTURE: { label: "Future", tone: "info", hint: "Applied to the database by a newer set of scripts." },
  BASELINE: { label: "Baseline", tone: "info", hint: "Marks where history starts for an existing database." },
  IGNORED: { label: "Ignored", tone: "muted", hint: "Skipped by the current filters." },
};

export function stateInfo(status: string): StateInfo {
  return STATES[status.toUpperCase()] ?? { label: status, tone: "info", hint: "" };
}

/** History can list a script several times (run, undone, run again): keep its latest entry. */
export function latestPerScript(migrations: Migration[]): Migration[] {
  const latest = new Map<string, Migration>();
  for (const migration of migrations) {
    latest.set(migration.script, migration);
  }
  return [...latest.values()];
}

export function summarize(migrations: Migration[]) {
  const count = (status: string) => migrations.filter((m) => m.status === status).length;
  return { applied: count("SUCCESS"), pending: count("PENDING"), failed: count("FAILED") };
}

/** How far the rail is filled: to the middle of the last applied node. */
export function railFill(migrations: Migration[]): number {
  const last = migrations.map((m) => m.status).lastIndexOf("SUCCESS");
  return last < 0 ? 0 : (last + 0.5) / migrations.length;
}
