import { useEffect, useId, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { runJob } from "../../api/jobs";
import { getScratchPlan } from "../../api/scratch";
import type { JobEvent, ScratchPhase, ScratchPlan } from "../../api/types";
import type { Outcome, StepProps } from "../../wizard/steps";

export const PHASE_LABELS: Record<ScratchPhase["name"], string> = {
  clean: "Empty the scratch database",
  build: "Build from zero",
  undo: "Undo the new migration",
  reapply: "Apply it again",
};

type State = "running" | "passed" | "failed" | "skipped";
interface Shown {
  name: ScratchPhase["name"];
  state: State;
  detail: string;
}

// Each state has its word and its sign: colour is never the only one.
const ICONS: Record<State, string> = { running: "…", passed: "✓", failed: "✗", skipped: "–" };
const stateOf = (ok: boolean | null): State => (ok === null ? "skipped" : ok ? "passed" : "failed");

// The server answers these before starting a job: nothing ran.
const NOT_STARTED = new Set([400, 404, 409]);

type Plan = { phase: "loading" } | { phase: "ready"; plan: ScratchPlan } | { phase: "error"; error: string };

/** Prove the migration and its undo script on a scratch database: build from zero, undo, re-apply. */
export default function TestStep({ context, onNext, onBack, last }: StepProps) {
  const { project, scripts, test, update } = context;
  const question = useId();
  const [plan, setPlan] = useState<Plan>({ phase: "loading" });
  const [phases, setPhases] = useState<Shown[]>([]);
  const [running, setRunning] = useState(false);
  // How the last run that finished ended, as shown here; the context keeps the outcome for the next steps.
  const [ended, setEnded] = useState<Outcome | null>(null);
  const [runs, setRuns] = useState(0);
  const [refused, setRefused] = useState<string | null>(null);
  // The job failed before the test could report anything.
  const [broken, setBroken] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    let current = true;
    getScratchPlan(project.id).then(
      (found) => current && setPlan({ phase: "ready", plan: found }),
      (failure: Error) => current && setPlan({ phase: "error", error: failure.message }),
    );
    return () => {
      current = false;
    };
  }, [project.id]);

  // Backing out of the question puts focus back on the button that asked it.
  const runButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (!asking && returnFocus.current) {
      runButton.current?.focus();
      returnFocus.current = false;
    }
  }, [asking]);

  const report = (event: JobEvent) => {
    if (event.event !== "scratch.phase" || !event.phase || !event.status) {
      return;
    }
    const shown: Shown = { name: event.phase, state: event.status === "started" ? "running" : event.status, detail: event.detail ?? "" };
    setPhases((list) => (list.some((p) => p.name === shown.name) ? list.map((p) => (p.name === shown.name ? shown : p)) : [...list, shown]));
  };

  const run = async () => {
    const before = { phases, ended };
    setAsking(false);
    setConfirmed(true);
    setPhases([]);
    setEnded(null);
    setRefused(null);
    setBroken(null);
    setRunning(true);
    // The job goes on on the server if the wizard closes, and holds the project: the wizard stays open until it ends.
    update({ busy: "The test is running…" });
    try {
      const result = await runJob(project.id, "scratch_test", "", report, { script: scripts?.migration });
      const found = result.scratch;
      const outcome: Outcome = found ? (found.passed ? "passed" : found.skipped ? "skipped" : "failed") : "failed";
      if (found) {
        setPhases(found.phases.map((p) => ({ name: p.name, state: stateOf(p.ok), detail: p.detail })));
      } else {
        setBroken(result.error ?? "The test could not be run.");
      }
      setEnded(outcome);
      setRuns((n) => n + 1);
      update({ test: { outcome, result: found } });
    } catch (failure) {
      setRefused((failure as Error).message);
      // Refused before it started: what was shown still holds.
      if (failure instanceof ApiError && NOT_STARTED.has(failure.status)) {
        setPhases(before.phases);
        setEnded(before.ended);
      }
    } finally {
      setRunning(false);
      update({ busy: null });
    }
  };

  const strategy = plan.phase === "ready" ? plan.plan.strategy : null;
  const runnable = strategy === "file" || strategy === "environment";
  const start = () => (strategy === "environment" && !confirmed ? setAsking(true) : void run());
  const cancel = () => {
    returnFocus.current = true;
    setAsking(false);
  };
  // After a failed run, going on without the test keeps it failed: it is never described as skipped.
  const goOn = () => {
    update({ test: { ...test, outcome: ended === "failed" || test.outcome === "failed" ? "failed" : "skipped" } });
    onNext();
  };
  // The scripts were saved again since the last run: its result is about the earlier content.
  const stale = !running && ended !== null && test.outcome === null;
  const failed = !running && !stale && ended === "failed";

  return (
    <div className="wizard__test">
      {plan.phase === "loading" && <p className="dialog__hint">Reading how the test will run…</p>}
      {plan.phase === "error" && (
        <p className="notice notice--error" role="alert">
          The test plan could not be read: {plan.error}
        </p>
      )}
      {plan.phase === "ready" && (
        <div className="wizard__plan">
          <p>{plan.plan.summary}</p>
          {runnable && <p className="dialog__hint">The test builds the database from zero, undoes the new migration, then applies it again.</p>}
          {plan.plan.warning && (
            <p className="wizard__warning" role="note">
              {plan.plan.warning}
            </p>
          )}
        </div>
      )}

      {phases.length > 0 && (
        <ol className="phases" aria-label="Test phases">
          {phases.map((p) => (
            <li key={p.name} className={`phase phase--${p.state}`}>
              <span className="phase__icon" aria-hidden="true">
                {ICONS[p.state]}
              </span>
              <span className="phase__name">{PHASE_LABELS[p.name]}</span>
              <span className="phase__state">{p.state}</span>
              {p.state === "failed" ? (
                <div className="wizard__failure" role="alert">
                  <p>{PHASE_LABELS[p.name]} failed.</p>
                  <pre className="mono">{p.detail}</pre>
                </div>
              ) : (
                p.detail && <p className="phase__detail">{p.detail}</p>
              )}
            </li>
          ))}
        </ol>
      )}
      {broken && (
        <div className="wizard__failure" role="alert">
          <p>The test could not run.</p>
          <pre className="mono">{broken}</pre>
        </div>
      )}
      {refused && (
        <p className="notice notice--error" role="alert">
          {refused}
        </p>
      )}

      <p className="wizard__outcome" role="status">
        {stale && "The scripts changed since this run. Run the test again."}
        {!stale && !running && ended === "passed" && "The test passed."}
        {!stale && !running && ended === "skipped" && "No scratch database was available: the test was skipped."}
      </p>

      {failed && runnable && (
        <div className="wizard__retry">
          <button className="button" onClick={onBack}>
            Back to the scripts
          </button>
          <button ref={runButton} className="button button--primary" onClick={start}>
            Run again
          </button>
        </div>
      )}

      {asking && (
        <div
          className="wizard__confirm"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.stopPropagation();
              cancel();
            }
          }}
        >
          <span id={question}>Empty the scratch environment and run the test?</span>
          <button className="button button--quiet" autoFocus onClick={cancel}>
            Cancel
          </button>
          <button className="button button--danger" aria-describedby={question} onClick={() => void run()}>
            Empty and run
          </button>
        </div>
      )}

      <div className="wizard__actions">
        <button type="button" className="button button--quiet wizard__back" onClick={onBack}>
          Back
        </button>
        <button className="button" disabled={running} onClick={goOn}>
          Continue without the test
        </button>
        {runnable && !failed && !asking && (
          <button
            ref={runButton}
            className={ended === "passed" && !stale ? "button" : "button button--primary"}
            disabled={running}
            onClick={start}
          >
            {runs > 0 ? "Run again" : "Run the test"}
          </button>
        )}
        {(runnable || test.outcome === "passed") && (
          <button
            className={test.outcome === "passed" ? "button button--primary" : "button"}
            disabled={running || test.outcome !== "passed"}
            onClick={onNext}
          >
            {last ? "Finish" : "Next"}
          </button>
        )}
      </div>
    </div>
  );
}
