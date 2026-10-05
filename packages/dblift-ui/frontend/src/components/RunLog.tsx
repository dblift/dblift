import { useState } from "react";

import { readJobLog } from "../api/jobs";
import type { CommandRun } from "../commands/useCommand";
import { describeEvent } from "../status/activity";

const TITLES: Record<string, string> = {
  migrate: "dblift migrate",
  undo: "dblift undo",
  validate: "dblift validate",
  repair: "dblift repair",
  baseline: "dblift baseline",
  preview: "dblift migrate --dry-run",
};

export default function RunLog({ run, onDismiss }: { run: CommandRun; onDismiss: () => void }) {
  const lines = run.events.filter((event) => event.event !== "job.finished");
  const [full, setFull] = useState<{ open: boolean; text: string | null; error: string | null }>({ open: false, text: null, error: null });
  const jobId = run.result?.has_log ? run.result.job_id : null;

  const toggleFull = async () => {
    if (full.open) {
      setFull((f) => ({ ...f, open: false }));
      return;
    }
    setFull((f) => ({ ...f, open: true, error: null }));
    if (full.text === null && jobId) {
      try {
        const text = await readJobLog(jobId);
        setFull((f) => ({ ...f, text }));
      } catch (failure) {
        setFull((f) => ({ ...f, error: (failure as Error).message }));
      }
    }
  };
  return (
    <section className="runlog rise">
      <header className="runlog__head">
        <span className="mono runlog__title">$ {TITLES[run.command] ?? run.command}</span>
        {jobId && (
          <button className="button button--quiet" onClick={() => void toggleFull()}>
            {full.open ? "Hide full log" : "Full log"}
          </button>
        )}
        <button className="button button--quiet" onClick={onDismiss} disabled={run.phase === "running"}>
          Close log
        </button>
      </header>
      <div className="runlog__body mono" role="log" aria-live="polite">
        {lines.map((event, index) => (
          <p key={index} className={event.error ? "runlog__line runlog__line--error" : "runlog__line"}>
            {describeEvent(event)}
          </p>
        ))}
        {run.phase === "running" && <p className="runlog__line runlog__line--muted">…</p>}
        {run.phase === "done" && <p className="runlog__line runlog__line--ok">✓ done</p>}
        {run.phase === "failed" && <p className="runlog__line runlog__line--error">✗ {run.error}</p>}
      </div>
      {full.open && full.error && (
        <p className="notice notice--error" role="alert">
          {full.error}
        </p>
      )}
      {full.open && full.text !== null && <pre className="runlog__full mono">{full.text}</pre>}
    </section>
  );
}
