import type { Migration } from "../api/types";

export type Tone = "ok" | "warn" | "error" | "info" | "muted";

interface StateInfo {
  label: string;
  tone: Tone;
  hint: string;
  /** True when the migration's effect is present in the database. */
  applied: boolean;
}

// Keyed by the state string the engine reports, with spaces as underscores.
// FUTURE and IGNORED have not been observed; anything unlisted is shown as is.
const STATES: Record<string, StateInfo> = {
  SUCCESS: { label: "Applied", tone: "ok", applied: true, hint: "Ran successfully on this database." },
  PENDING: { label: "Pending", tone: "warn", applied: false, hint: "Not yet run on this database." },
  RUNNING: { label: "Running", tone: "info", applied: false, hint: "Being applied right now." },
  FAILED: { label: "Failed", tone: "error", applied: false, hint: "Stopped with an error. Repair before migrating again." },
  UNDONE: { label: "Undone", tone: "muted", applied: false, hint: "Was applied, then reverted by its undo script." },
  MISSING: { label: "Missing", tone: "error", applied: true, hint: "Applied to the database, but its file is not in this folder." },
  OUT_OF_ORDER: { label: "Out of order", tone: "warn", applied: true, hint: "Applied after a later version." },
  BASELINE: { label: "Baseline", tone: "info", applied: true, hint: "Marks where history starts for an existing database." },
  BELOW_BASELINE: { label: "Below baseline", tone: "muted", applied: false, hint: "Older than the baseline, so it is not run." },
  FUTURE: { label: "Future", tone: "info", applied: true, hint: "Applied to the database by a newer set of scripts." },
  IGNORED: { label: "Ignored", tone: "muted", applied: false, hint: "Skipped by the current filters." },
};

export function stateInfo(status: string): StateInfo {
  const key = status.trim().toUpperCase().replaceAll(" ", "_");
  return STATES[key] ?? { label: status, tone: "info", applied: false, hint: "" };
}

export const isApplied = (status: string) => stateInfo(status).applied;

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
  return {
    applied: migrations.filter((m) => isApplied(m.status)).length,
    pending: count("PENDING"),
    failed: count("FAILED"),
  };
}

/** How far the rail is filled: to the middle of the last applied node. */
export function railFill(migrations: Migration[]): number {
  const last = migrations.map((m) => isApplied(m.status)).lastIndexOf(true);
  return last < 0 ? 0 : (last + 0.5) / migrations.length;
}
