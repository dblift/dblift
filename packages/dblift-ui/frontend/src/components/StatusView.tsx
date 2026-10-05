import { useState } from "react";

import type { Project } from "../api/types";
import { describeActivity } from "../status/activity";
import { latestPerScript, summarize } from "../status/model";
import { useStatus } from "../status/useStatus";
import EngineLogo from "./EngineLogo";
import MigrationGrid from "./MigrationGrid";
import Rail from "./Rail";

interface Props {
  project: Project;
  /** May return a promise; a rejection is shown to the user. */
  onEnvironmentChange: (environment: string) => void | Promise<unknown>;
}

export default function StatusView({ project, onEnvironmentChange }: Props) {
  const [environment, setEnvironment] = useState(project.last_environment);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { phase, result, error, activity, refresh } = useStatus(project.id, environment);
  const migrations = latestPerScript(result?.migrations ?? []);
  const counts = summarize(migrations);

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
                onClick={() => choose(name)}
              >
                {name || "default"}
              </button>
            ))}
          </div>
          <button className="button" onClick={refresh} disabled={phase === "loading"}>
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
