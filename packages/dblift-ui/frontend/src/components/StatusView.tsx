import { useState } from "react";

import type { Project, SqlPreview } from "../api/types";
import { liveStates } from "../commands/live";
import { useCommand } from "../commands/useCommand";
import { describeActivity } from "../status/activity";
import { latestPerScript, summarize } from "../status/model";
import { useStatus } from "../status/useStatus";
import CommandBar from "./CommandBar";
import EngineLogo from "./EngineLogo";
import MigrationGrid from "./MigrationGrid";
import PreviewPanel from "./PreviewPanel";
import Rail from "./Rail";
import RunLog from "./RunLog";

interface Props {
  project: Project;
  /** May return a promise; a rejection is shown to the user. */
  onEnvironmentChange: (environment: string) => void | Promise<unknown>;
}

export default function StatusView({ project, onEnvironmentChange }: Props) {
  const [environment, setEnvironment] = useState(project.last_environment);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { phase, result, error, activity, refresh } = useStatus(project.id, environment);
  const { run, busy, start, dismiss } = useCommand(project.id, environment, refresh);
  const [preview, setPreview] = useState<SqlPreview[] | null>(null);
  const changing = busy && run !== null && run.command !== "validate" && run.command !== "preview";
  // The SQL shown must be the SQL that runs: the environment stays put while it is read or shown.
  const previewing = preview !== null || (busy && run?.command === "preview");
  const live = run && run.phase === "running" ? liveStates(run.events) : {};
  const migrations = latestPerScript(result?.migrations ?? []).map((m) =>
    live[m.script] ? { ...m, status: live[m.script] } : m,
  );
  const counts = summarize(migrations);

  const openPreview = async () => {
    const answer = await start("preview");
    if (answer?.success) {
      setPreview(answer.sql);
      dismiss();
    }
  };
  const apply = () => {
    setPreview(null);
    void start("migrate");
  };

  const choose = (name: string) => {
    setEnvironment(name);
    setSaveError(null);
    Promise.resolve(onEnvironmentChange(name)).catch((failure: Error) => {
      setSaveError(`The chosen environment could not be remembered: ${failure.message}`);
    });
  };

  return (
    <section className="status" aria-busy={phase === "loading"}>
      <header className="status__head rise">
        <div>
          <p className="eyebrow">
            <EngineLogo engine={project.engine} size={14} />
            {project.engine || "project"}
          </p>
          <h1>{project.name}</h1>
          <p className="status__path mono" title={project.config_path}>
            {project.config_path}
          </p>
        </div>
        <div className="status__actions">
          <div className="segmented" role="tablist" aria-label="Environment">
            {["", ...project.environments].map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={name === environment}
                className="segmented__item"
                disabled={changing || previewing}
                onClick={() => choose(name)}
              >
                {name || "default"}
              </button>
            ))}
          </div>
          <button className="button" onClick={refresh} disabled={phase === "loading" || changing}>
            Refresh
          </button>
        </div>
      </header>

      {project.error && (
        <p className="notice notice--error" role="alert">
          This project's config has a problem: {project.error}
        </p>
      )}
      {!project.error && phase === "error" && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      {saveError && (
        <p className="notice notice--error" role="alert">
          {saveError}
        </p>
      )}

      {!project.error && result && phase !== "error" && (
        <CommandBar
          counts={counts}
          hasVersion={result.current_version !== null}
          busy={busy || preview !== null}
          onMigrate={() => void openPreview()}
          onCommand={(command, params) => void start(command, params)}
        />
      )}

      {preview && <PreviewPanel preview={preview} busy={busy} onApply={apply} onCancel={() => setPreview(null)} />}

      {run && (run.command !== "preview" || run.phase === "failed") && <RunLog run={run} onDismiss={dismiss} />}

      {result && phase !== "error" && (
        <>
          <div className="summary rise" style={{ "--order": 1 } as React.CSSProperties}>
            <dl className="summary__stats">
              <div>
                <dt>Version</dt>
                <dd>{result.current_version ?? "—"}</dd>
              </div>
              <div>
                <dt>Applied</dt>
                <dd>{counts.applied}</dd>
              </div>
              <div>
                <dt>Pending</dt>
                <dd>{counts.pending}</dd>
              </div>
              {counts.failed > 0 && (
                <div>
                  <dt>Failed</dt>
                  <dd className="summary__failed">{counts.failed}</dd>
                </div>
              )}
            </dl>
            {migrations.length > 0 && <Rail migrations={migrations} />}
          </div>

          {migrations.length > 0 ? (
            <div className="panel rise" style={{ "--order": 2 } as React.CSSProperties}>
              <MigrationGrid migrations={migrations} />
            </div>
          ) : (
            <p className="notice">No migrations found in this project.</p>
          )}
        </>
      )}

      <p className="status__activity mono" aria-live="polite">
        {phase === "loading" ? (activity ? describeActivity(activity) : "Reading migration status…") : ""}
      </p>
    </section>
  );
}
