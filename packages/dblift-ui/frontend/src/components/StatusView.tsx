import { useQuery, useQueryClient } from "@tanstack/react-query";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { commitFiles, createBranch, fetchRepo, getBranches, pullRepo, pushRepo, switchBranch } from "../api/git";
import { listScripts } from "../api/scripts";
import type { Project, RepoStatus, SqlPreview } from "../api/types";
import { liveStates } from "../commands/live";
import { useCommand } from "../commands/useCommand";
import { changedScriptFiles } from "../git/changes";
import { useRepo } from "../git/useRepo";
import { describeActivity } from "../status/activity";
import { isApplied, latestPerScript, summarize, undoNameOf } from "../status/model";
import { useStatus } from "../status/useStatus";
import BranchChip from "./BranchChip";
import CommandBar from "./CommandBar";
import CommitDialog from "./CommitDialog";
import EngineLogo from "./EngineLogo";
import FlywayImport from "./FlywayImport";
import MigrationGrid from "./MigrationGrid";
import NewMigration from "./NewMigration";
import PreviewPanel from "./PreviewPanel";
import Rail from "./Rail";
import RunLog from "./RunLog";
import ScriptPanel, { type ScriptPanelHandle } from "./ScriptPanel";
import Wizard from "./wizard/Wizard";

interface Props {
  project: Project;
  /** May return a promise; a rejection is shown to the user. */
  onEnvironmentChange: (environment: string) => void | Promise<unknown>;
  /** Open the project's configuration; without it, the header offers no "Configuration" button. */
  onConfigure?: () => void;
  /**
   * Called after a switch, a new branch or a pull: the working tree may hold other files now.
   * The app then re-reads its projects and this view; without it, the view re-reads itself.
   */
  onMoved?: () => void;
}

/** Lets the app ask before it replaces the view, as the editor's own controls do. */
export interface StatusViewHandle {
  leave(action: () => void): void;
  /** Read the status and the scripts again, after the project's configuration changed. */
  reread(): void;
}

const StatusView = forwardRef<StatusViewHandle, Props>(function StatusView({ project, onEnvironmentChange, onConfigure, onMoved }, ref) {
  const [environment, setEnvironment] = useState(project.last_environment);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Every finished job reads the repository again: a file it left while running (a SQLite
  // journal) must not stay listed as uncommitted.
  const { phase, result, error, activity, refresh } = useStatus(project.id, environment, () => git.refresh());
  const queryClient = useQueryClient();
  // Re-read on focus too: the uncommitted marks follow commits made with another tool.
  const { data: scripts = [], dataUpdatedAt: scriptsRead } = useQuery({
    queryKey: ["scripts", project.id],
    queryFn: () => listScripts(project.id),
    refetchOnWindowFocus: true,
  });
  const rereadScripts = () => queryClient.invalidateQueries({ queryKey: ["scripts", project.id] });
  // The script list and the repository change with the files, so they are re-read whenever the status is.
  const refreshAll = () => {
    refresh();
    void rereadScripts();
    git.refresh();
  };
  // After a move, the open script is read again from the new files, or closed when it is not there.
  const followMove = useRef(false);
  const [moves, setMoves] = useState(0);
  const git = useRepo(project.id, () => {
    followMove.current = true;
    if (onMoved) {
      onMoved();
    } else {
      refreshAll();
    }
  });
  const { run, busy, start, dismiss } = useCommand(project.id, environment, refreshAll, git.refresh);
  const [openScript, setOpenScript] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [wizard, setWizard] = useState(false);
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

  // Runs on each new read of the script list; only the first one after a move acts.
  useEffect(() => {
    if (!followMove.current) {
      return;
    }
    followMove.current = false;
    setOpenScript((current) => (current && scripts.some((s) => s.name === current) ? current : null));
    setMoves((n) => n + 1);
  }, [scriptsRead]);

  const moveWith = (verb: () => Promise<RepoStatus>) => leaveEditor(() => void git.act(verb, true));

  const [committing, setCommitting] = useState(false);
  // The names of the project's scripts, migrations and undo scripts, not committed as they are.
  const changedScripts = scripts.flatMap((s) => [...(s.change ? [s.name] : []), ...(s.undo_change ? [undoNameOf(s.name)] : [])]);
  // Ticked when the commit opens: this project's changed scripts and its config file.
  const ownChanges = () => {
    const root = (git.repo?.root ?? "").replaceAll("\\", "/");
    const config = project.config_path.replaceAll("\\", "/");
    const configFile = root && config.startsWith(`${root}/`) ? config.slice(root.length + 1) : null;
    const files = git.repo?.files ?? [];
    return [...files.filter((f) => f.path === configFile).map((f) => f.path), ...changedScriptFiles(files, scripts)];
  };
  const commit = async (paths: string[], message: string) => {
    if (await git.act(() => commitFiles(project.id, paths, message))) {
      setCommitting(false);
      void rereadScripts();
    }
  };
  const closeCommit = () => {
    setCommitting(false);
    git.dismissError();
  };

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
          {git.repo?.repository && (
            <BranchChip
              repo={git.repo}
              busy={git.busy}
              error={committing ? null : git.error}
              locked={changing || previewing}
              loadBranches={() => getBranches(project.id)}
              onSwitch={(name) => moveWith(() => switchBranch(project.id, name))}
              onCreate={(name) => moveWith(() => createBranch(project.id, name))}
              onFetch={() => void git.act(() => fetchRepo(project.id))}
              onPull={() => moveWith(() => pullRepo(project.id))}
              onPush={() => void git.act(() => pushRepo(project.id))}
              onCommit={() => {
                git.dismissError();
                setCommitting(true);
              }}
              onDismissError={git.dismissError}
            />
          )}
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
          onNewChange={() =>
            leaveEditor(() => {
              setOpenScript(null);
              setWizard(true);
            })
          }
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

      {wizard && <Wizard project={project} onClose={() => setWizard(false)} onChanged={refreshAll} />}

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
          key={`${openScript}:${moves}`}
          ref={panel}
          projectId={project.id}
          script={openScript}
          applied={opened ? isApplied(opened.status) : false}
          hasUndo={scripts.some((s) => s.name === openScript && s.has_undo)}
          locked={changing}
          previewing={previewing}
          changed={changedScripts}
          onClose={() => setOpenScript(null)}
          onSaved={refreshAll}
        />
      )}

      {committing && git.repo?.repository && (
        <CommitDialog
          files={git.repo.files ?? []}
          preselected={ownChanges()}
          busy={git.busy}
          error={git.error}
          truncated={git.repo.truncated}
          onCommit={(paths, message) => void commit(paths, message)}
          onClose={closeCommit}
        />
      )}

      <p className="status__activity mono" aria-live="polite">
        {phase === "loading" ? (activity ? describeActivity(activity) : "Reading migration status…") : ""}
      </p>
    </section>
  );
});

export default StatusView;
