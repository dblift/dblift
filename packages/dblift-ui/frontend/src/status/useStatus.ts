import { useCallback, useEffect, useRef, useState } from "react";

import { runJob } from "../api/jobs";
import type { JobResult } from "../api/types";

type Phase = "loading" | "ready" | "error";

interface Status {
  phase: Phase;
  result: JobResult | null;
  error: string | null;
  activity: string;
}

const LOADING: Status = { phase: "loading", result: null, error: null, activity: "" };

/** Run the status job for a project and environment; re-run on demand. *onRead* runs after each read. */
export function useStatus(projectId: string, environment: string, onRead?: () => void) {
  const [status, setStatus] = useState<Status>(LOADING);
  const [run, setRun] = useState(0);
  const read = useRef(onRead);
  read.current = onRead;

  useEffect(() => {
    let current = true;
    setStatus((previous) => ({ ...LOADING, result: previous.result }));
    runJob(projectId, "info", environment, (event) => {
      if (current) {
        setStatus((previous) => ({ ...previous, activity: event.event }));
      }
    })
      .then((result) => {
        if (!current) {
          return;
        }
        setStatus(
          result.success
            ? { phase: "ready", result, error: null, activity: "" }
            : { phase: "error", result, error: result.error ?? "status failed", activity: "" },
        );
      })
      .catch((failure: Error) => {
        if (current) {
          setStatus({ phase: "error", result: null, error: failure.message, activity: "" });
        }
      })
      .finally(() => read.current?.());
    return () => {
      current = false;
    };
  }, [projectId, environment, run]);

  const refresh = useCallback(() => setRun((n) => n + 1), []);
  return { ...status, refresh };
}
