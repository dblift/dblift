import { forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";

import { useScript } from "../scripts/useScript";
import { undoNameOf } from "../status/model";

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
  onClose: () => void;
  onSaved: () => void;
}

/** Lets the view ask before it replaces the panel, as the panel's own tabs and Close do. */
export interface ScriptPanelHandle {
  leave(action: () => void): void;
}

type Tab = "migration" | "undo";

const ScriptPanel = forwardRef<ScriptPanelHandle, Props>(function ScriptPanel(
  { projectId, script, applied, hasUndo, locked, previewing = false, onClose, onSaved },
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
      {error && phase !== "missing" && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      <div className="script__body">
        {phase === "loading" && <p className="script__message">Opening…</p>}
        {phase === "missing" && tab === "undo" && (
          <p className="script__message">This migration has no undo script.{hasUndo ? " It may have been removed." : ""}</p>
        )}
        {phase === "missing" && tab === "migration" && <p className="script__message">This file is no longer in the project.</p>}
        {phase === "ready" && file && (
          <Suspense fallback={<p className="script__message">Opening…</p>}>
            <CodeEditor value={content} language={file.language} label={`Content of ${file.name}`} readOnly={saving || previewing} onChange={edit} />
          </Suspense>
        )}
      </div>
    </section>
  );
});

export default ScriptPanel;
