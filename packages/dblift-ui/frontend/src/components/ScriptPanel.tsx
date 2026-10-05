import { forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";

import { scriptDiff } from "../api/git";
import { useScript } from "../scripts/useScript";
import { undoNameOf } from "../status/model";
import DiffView from "./DiffView";

// The editor is most of the app's code: it loads the first time a script is opened.
const CodeEditor = lazy(() => import("./CodeEditor"));

interface Props {
  projectId: string;
  /** File name of the migration (not of its undo script). */
  script: string;
  applied: boolean;
  hasUndo: boolean;
  /** True while a change runs on the project: nothing may be saved. */
  locked: boolean;
  /** True while the SQL preview is read or shown: what is applied must be what was shown. */
  previewing?: boolean;
  /** Names of the project's scripts not committed as they are: those offer their changes. */
  changed?: string[];
  onClose: () => void;
  onSaved: () => void;
}

/** Lets the view ask before it replaces the panel, as the panel's own tabs and Close do. */
export interface ScriptPanelHandle {
  leave(action: () => void): void;
}

type Tab = "migration" | "undo";

/** The changes of the file shown since the last commit, while the "Changes" toggle is on. */
type Changes = { phase: "loading" } | { phase: "ready"; diff: string } | { phase: "error"; error: string };

const ScriptPanel = forwardRef<ScriptPanelHandle, Props>(function ScriptPanel(
  { projectId, script, applied, hasUndo, locked, previewing = false, changed = [], onClose, onSaved },
  ref,
) {
  const [tab, setTab] = useState<Tab>("migration");
  const [pending, setPending] = useState<null | (() => void)>(null);
  // Only a versioned migration has an undo script; a repeatable one has no "U…" name.
  const versioned = script.startsWith("V");
  const name = tab === "migration" ? script : undoNameOf(script);
  const { phase, file, content, dirty, saving, error, edit, save } = useScript(projectId, name);
  // Where focus was when the question came up, to return there on "Keep editing".
  const asker = useRef<HTMLElement | null>(null);
  const [showChanges, setShowChanges] = useState(false);
  const [changes, setChanges] = useState<Changes>({ phase: "loading" });
  const [saves, setSaves] = useState(0);
  const hasChanges = changed.includes(name);
  const showing = showChanges && hasChanges;

  // Read when the toggle is turned on, for the file of the tab shown, and again after a save.
  useEffect(() => {
    if (!showing) {
      return;
    }
    let current = true;
    setChanges({ phase: "loading" });
    scriptDiff(projectId, name)
      .then((diff) => current && setChanges({ phase: "ready", diff }))
      .catch((failure: Error) => current && setChanges({ phase: "error", error: failure.message }));
    return () => {
      current = false;
    };
  }, [showing, projectId, name, saves]);

  // Leaving unsaved edits needs a second click.
  const leave = (action: () => void) => {
    if (dirty) {
      asker.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setPending(() => action);
    } else {
      action();
    }
  };
  useImperativeHandle(ref, () => ({ leave }));

  // Reloading or closing the page with unsaved edits gets the browser's own question.
  useEffect(() => {
    if (!dirty) {
      return;
    }
    const ask = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", ask);
    return () => window.removeEventListener("beforeunload", ask);
  }, [dirty]);
  const keepEditing = () => {
    setPending(null);
    asker.current?.focus();
  };
  const saveNow = async () => {
    if (await save()) {
      setSaves((n) => n + 1);
      onSaved();
    }
  };

  return (
    <section className="script panel rise" aria-label={`Editor for ${script}`}>
      <header className="script__head">
        {versioned && (
          <div className="segmented" role="tablist" aria-label="Script">
            <button role="tab" aria-selected={tab === "migration"} className="segmented__item" onClick={() => tab !== "migration" && leave(() => setTab("migration"))}>
              Migration
            </button>
            <button role="tab" aria-selected={tab === "undo"} className="segmented__item" onClick={() => tab !== "undo" && leave(() => setTab("undo"))}>
              Undo script
            </button>
          </div>
        )}
        <span className="script__name mono" title={name}>
          {name}
        </span>
        <div className="script__actions">
          {hasChanges && (
            <button className="button button--quiet" aria-pressed={showing} onClick={() => setShowChanges(!showing)}>
              Changes
            </button>
          )}
          <button className="button button--primary" disabled={!dirty || saving || locked || previewing} onClick={() => void saveNow()}>
            Save
          </button>
          <button className="button button--quiet" onClick={() => leave(onClose)}>
            Close editor
          </button>
        </div>
      </header>

      {pending && (
        <div className="script__guard">
          <span>Discard your changes?</span>
          <button className="button button--quiet" autoFocus onClick={keepEditing}>
            Keep editing
          </button>
          <button
            className="button button--danger"
            onClick={() => {
              const action = pending;
              setPending(null);
              action();
            }}
          >
            Discard
          </button>
        </div>
      )}

      {tab === "migration" && applied && (
        <p className="script__warning" role="note">
          This migration is already applied to this database. Saving a change alters its checksum, and
          validation will fail until the database and the file agree again.
        </p>
      )}
      {locked ? (
        <p className="script__lock">A change is running on this project. Saving is paused until it ends.</p>
      ) : (
        previewing && <p className="script__lock">Close the SQL preview before editing: what is applied must be what was shown.</p>
      )}
      {showing && changes.phase === "error" && (
        <p className="notice notice--error" role="alert">
          {changes.error}
        </p>
      )}
      {showing && dirty && <p className="script__lock">Unsaved edits are not part of these changes until they are saved.</p>}
      {error && phase !== "missing" && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      <div className="script__body">
        {!showing && phase === "loading" && <p className="script__message">Opening…</p>}
        {phase === "missing" && tab === "undo" && (
          <p className="script__message">This migration has no undo script.{hasUndo ? " It may have been removed." : ""}</p>
        )}
        {phase === "missing" && tab === "migration" && <p className="script__message">This file is no longer in the project.</p>}
        {showing && changes.phase === "loading" && <p className="script__message">Reading the changes…</p>}
        {showing && changes.phase === "ready" &&
          (changes.diff ? <DiffView diff={changes.diff} /> : <p className="script__message">No change since the last commit.</p>)}
        {!showing && phase === "ready" && file && (
          <Suspense fallback={<p className="script__message">Opening…</p>}>
            <CodeEditor value={content} language={file.language} label={`Content of ${file.name}`} readOnly={saving || previewing} onChange={edit} />
          </Suspense>
        )}
      </div>
    </section>
  );
});

export default ScriptPanel;
