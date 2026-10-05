import { lazy, type ReactNode, Suspense, useEffect, useId, useState } from "react";

import { useScript } from "../../scripts/useScript";
import type { StepProps } from "../../wizard/steps";

// The editor is most of the app's code: it loads the first time a script is opened.
const CodeEditor = lazy(() => import("../CodeEditor"));

type Loaded = ReturnType<typeof useScript>;

function Editor({ title, name, script, readOnly, children }: { title: string; name: string | null; script: Loaded; readOnly: boolean; children?: ReactNode }) {
  const heading = useId();
  return (
    <section className="wizard__editor" aria-labelledby={heading}>
      <header className="wizard__editor-head">
        <h4 id={heading}>{title}</h4>
        {name && (
          <span className="wizard__file mono" title={name}>
            {name}
          </span>
        )}
      </header>
      {script.error && (
        <p className="notice notice--error" role="alert">
          {script.error}
        </p>
      )}
      <div className="wizard__code">
        {name === null && <p className="script__message">This migration has no undo script.</p>}
        {script.phase === "loading" && <p className="script__message">Opening…</p>}
        {script.phase === "ready" && script.file && (
          <Suspense fallback={<p className="script__message">Opening…</p>}>
            <CodeEditor
              value={script.content}
              language={script.file.language}
              label={`Content of ${script.file.name}`}
              readOnly={readOnly}
              onChange={script.edit}
            />
          </Suspense>
        )}
      </div>
      {children}
    </section>
  );
}

/** The migration and its undo script, side by side, saved on Next. */
export default function WriteStep({ context, onNext, onBack, last }: StepProps) {
  const { project, scripts, test, unsaved, update, changed } = context;
  const migration = useScript(project.id, scripts?.migration ?? null);
  const undo = useScript(project.id, scripts?.undo ?? null);
  const [saving, setSaving] = useState(false);
  const dirty = migration.dirty || undo.dirty;

  // The wizard asks before closing over unsaved edits, and opens no later step while they last.
  useEffect(() => {
    if (dirty !== unsaved) {
      update({ unsaved: dirty });
    }
  }, [dirty]);

  /** Save what changed; false when a save was refused. */
  const saveAll = async () => {
    let saved = false;
    let ok = true;
    for (const file of [migration, undo]) {
      if (file.dirty) {
        if (!(await file.save())) {
          ok = false;
          break;
        }
        saved = true;
      }
    }
    // A test or a commit of the earlier content says nothing about the new one.
    if (saved) {
      changed();
      update({ test: { ...test, outcome: null }, committed: false, published: false });
    }
    return ok;
  };

  const next = async () => {
    setSaving(true);
    const ok = await saveAll();
    setSaving(false);
    if (ok) {
      update({ written: true, unsaved: false });
      onNext();
    }
  };

  return (
    <div className="wizard__write">
      {/* Escape belongs to the editor here (Escape then Tab leaves it): it does not close the wizard. */}
      <div
        className="wizard__editors"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
          }
        }}
      >
        <Editor title="Migration" name={scripts?.migration ?? null} script={migration} readOnly={saving} />
        <Editor title="Undo script" name={scripts?.undo ?? null} script={undo} readOnly={saving}>
          <p className="wizard__hint">The undo script must leave the database as it was before the migration.</p>
        </Editor>
      </div>
      <div className="wizard__actions">
        <button type="button" className="button button--quiet wizard__back" onClick={onBack}>
          Back
        </button>
        <button className="button button--primary" disabled={saving || migration.saving || undo.saving} onClick={() => void next()}>
          {last ? "Finish" : "Next"}
        </button>
      </div>
    </div>
  );
}
