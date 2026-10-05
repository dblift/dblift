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
  return (
    <section className="runlog rise">
      <header className="runlog__head">
        <span className="mono">$ {TITLES[run.command] ?? run.command}</span>
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
    </section>
  );
}
