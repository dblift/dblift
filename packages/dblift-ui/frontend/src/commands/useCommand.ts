import { useCallback, useRef, useState } from "react";

import { ApiError } from "../api/client";
import { runJob } from "../api/jobs";
import type { JobEvent, JobResult } from "../api/types";

const MUTATING = new Set(["migrate", "undo", "repair", "baseline", "flyway_import"]);

// The server answers these before starting a job: nothing ran, so nothing changed.
const NOT_STARTED = new Set([400, 404, 409]);
const refused = (failure: unknown) => failure instanceof ApiError && NOT_STARTED.has(failure.status);

export interface CommandRun {
  command: string;
  phase: "running" | "done" | "failed";
  events: JobEvent[];
  result: JobResult | null;
  error: string | null;
}

/** Run one command at a time for a project and keep what it reported. */
export function useCommand(projectId: string, environment: string, onChanged: () => void) {
  const [run, setRun] = useState<CommandRun | null>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const start = useCallback(
    async (command: string, params: Record<string, unknown> = {}): Promise<JobResult | null> => {
      setRun({ command, phase: "running", events: [], result: null, error: null });
      try {
        const result = await runJob(
          projectId,
          command,
          environment,
          (event) => setRun((current) => (current ? { ...current, events: [...current.events, event] } : current)),
          params,
        );
        setRun((current) =>
          current && {
            ...current,
            phase: result.success ? "done" : "failed",
            result,
            error: result.success ? null : (result.error ?? `${command} failed`),
          },
        );
        if (MUTATING.has(command)) {
          changed.current();
        }
        return result;
      } catch (failure) {
        setRun((current) => current && { ...current, phase: "failed", error: (failure as Error).message });
        // Any other failure may have come after the job started: the database may have changed.
        if (MUTATING.has(command) && !refused(failure)) {
          changed.current();
        }
        return null;
      }
    },
    [projectId, environment],
  );

  const dismiss = useCallback(() => setRun(null), []);
  return { run, busy: run?.phase === "running", start, dismiss };
}
