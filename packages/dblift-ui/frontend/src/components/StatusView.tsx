import { useQuery, useQueryClient } from "@tanstack/react-query";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";

import { listScripts } from "../api/scripts";
import type { Project, SqlPreview } from "../api/types";
import { liveStates } from "../commands/live";
import { useCommand } from "../commands/useCommand";
import { describeActivity } from "../status/activity";
import { isApplied, latestPerScript, summarize } from "../status/model";
import { useStatus } from "../status/useStatus";
import CommandBar from "./CommandBar";
import EngineLogo from "./EngineLogo";
import FlywayImport from "./FlywayImport";
import MigrationGrid from "./MigrationGrid";
import NewMigration from "./NewMigration";
import PreviewPanel from "./PreviewPanel";
import Rail from "./Rail";
import RunLog from "./RunLog";
import ScriptPanel, { type ScriptPanelHandle } from "./ScriptPanel";

interface Props {
  project: Project;
  /** May return a promise; a rejection is shown to the user. */
  onEnvironmentChange: (environment: string) => void | Promise<unknown>;
  /** Open the project's configuration; without it, the header offers no "Configuration" button. */
  onConfigure?: () => void;
}

/** Lets the app ask before it replaces the view, as the editor's own controls do. */
export interface StatusViewHandle {
  leave(action: () => void): void;
  /** Read the status and the scripts again, after the project's configuration changed. */
  reread(): void;
}

const StatusView = forwardRef<StatusViewHandle, Props>(function StatusView({ project, onEnvironmentChange, onConfigure }, ref) {
  const [environment, setEnvironment] = useState(project.last_environment);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { phase, result, error, activity, refresh } = useStatus(project.id, environment);
  const queryClient = useQueryClient();
  const { data: scripts = [] } = useQuery({ queryKey: ["scripts", project.id], queryFn: () => listScripts(project.id) });
  const rereadScripts = () => queryClient.invalidateQueries({ queryKey: ["scripts", project.id] });
  // The script list changes with the files, so it is re-read whenever the status is.
  const refreshAll = () => {
    refresh();
    void rereadScripts();
  };
  const { run, busy, start, dismiss } = useCommand(project.id, environment, refreshAll);
  const [openScript, setOpenScript] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // Opening another script or a new one replaces the editor: it asks first when there are unsaved edits.
  const panel = useRef<ScriptPanelHandle>(null);
  const leaveEditor = (action: () => void) => (panel.current ? panel.current.leave(action) : action());
  useImperativeHandle(ref, () => ({ leave: leaveEditor, reread: refreshAll }));
  const [preview, setPreview] = useState<SqlPreview[] | null>(null);
  const changing = busy && run !== null && run.command !== "validate" && run.command !== "preview";
  // The SQL shown must be the SQL that runs: the environment stays put while it is read or shown.
  const previewing = preview !== null || (busy && run?.command === "preview");
  const live = run && run.phase === "running" ? liveStates(run.events) : {};
  const migrations = latestPerScript(result?.migrations ?? []).map((m) =>
    live[m.script] ? { ...m, status: live[m.script] } : m,
  );
  const counts = summarize(migrations);
  const opened = migrations.find((m) => m.script === openScript);

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
          <button className="button" onClick={refreshAll} disabled={phase === "loading" || changing}>
            Refresh
          </button>
          {onConfigure && (
            <button className="button" onClick={() => leaveEditor(onConfigure)} disabled={changing || previewing}>
              Configuration
            </button>
          )}
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

      {!project.error && result && phase !== "error" && project.flyway_table && counts.applied === 0 && (
        <FlywayImport
          table={project.flyway_table}
          busy={busy || preview !== null}
          run={run}
          onPreview={() => void start("flyway_preview", { table: project.flyway_table })}
          onImport={() => void start("flyway_import", { table: project.flyway_table })}
        />
      )}

      {!project.error && result && phase !== "error" && (
        <CommandBar
          counts={counts}
          hasVersion={result.current_version !== null}
          busy={busy || preview !== null}
          onMigrate={() => void openPreview()}
          onCommand={(command, params) => void start(command, params)}
          onNew={() =>
            leaveEditor(() => {
              setOpenScript(null);
              setCreating(true);
            })
          }
        />
      )}

      {creating && (
        <NewMigration
          projectId={project.id}
          locked={changing}
          previewing={previewing}
          onCancel={() => setCreating(false)}
          onCreated={(names) => {
            setCreating(false);
            setOpenScript(names[0]);
            refreshAll();
          }}
        />
      )}

      {preview && <PreviewPanel preview={preview} busy={busy} onApply={apply} onCancel={() => setPreview(null)} />}

      {run && (run.command !== "preview" || run.phase === "failed") && <RunLog key={run.result?.job_id ?? run.command} run={run} onDismiss={dismiss} />}

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
              <MigrationGrid
                migrations={migrations}
                scripts={scripts}
                openScript={openScript}
                onOpen={(name) => name !== openScript && leaveEditor(() => setOpenScript(name))}
              />
            </div>
          ) : (
            <p className="notice">No migrations found in this project.</p>
          )}
        </>
      )}

      {/* Outside the status block: a failed re-read must not drop the edits in progress. */}
      {openScript && (
        <ScriptPanel
          key={openScript}
          ref={panel}
          projectId={project.id}
          script={openScript}
          applied={opened ? isApplied(opened.status) : false}
          hasUndo={scripts.some((s) => s.name === openScript && s.has_undo)}
          locked={changing}
          previewing={previewing}
          onClose={() => setOpenScript(null)}
          onSaved={refreshAll}
        />
      )}

      <p className="status__activity mono" aria-live="polite">
        {phase === "loading" ? (activity ? describeActivity(activity) : "Reading migration status…") : ""}
      </p>
    </section>
  );
});

export default StatusView;
