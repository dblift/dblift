const ACTIVITY: Record<string, string> = {
  "info.started": "Reading migration status…",
  "info.completed": "Status read",
};

/** Words for the latest event of the running status job. */
export function describeActivity(event: string): string {
  return ACTIVITY[event] ?? "Working…";
}
