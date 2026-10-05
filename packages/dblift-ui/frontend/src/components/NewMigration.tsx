import { type FormEvent, useState } from "react";

import { createScripts, type NewScripts } from "../api/scripts";

interface Props {
  projectId: string;
  onCreated: (names: string[]) => void;
  onCancel: () => void;
  /** True while a change runs on the project: nothing may be created. */
  locked?: boolean;
  /** True while the SQL preview is read or shown: what is applied must be what was shown. */
  previewing?: boolean;
}

export default function NewMigration({ projectId, onCreated, onCancel, locked = false, previewing = false }: Props) {
  const [kind, setKind] = useState<NewScripts["kind"]>("versioned");
  const [language, setLanguage] = useState<NewScripts["language"]>("sql");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (locked || previewing) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { created } = await createScripts(projectId, { kind, language, description });
      onCreated(created);
    } catch (failure) {
      setError((failure as Error).message);
      setBusy(false);
    }
  };

  return (
    <form className="newmigration panel rise" aria-label="New migration" onSubmit={(e) => void submit(e)}>
      <fieldset className="newmigration__choice">
        <legend>Kind</legend>
        <label>
          <input type="radio" name="kind" checked={kind === "versioned"} onChange={() => setKind("versioned")} />
          Versioned, with its undo script
        </label>
        <label>
          <input type="radio" name="kind" checked={kind === "repeatable"} onChange={() => setKind("repeatable")} />
          Repeatable
        </label>
      </fieldset>
      <fieldset className="newmigration__choice">
        <legend>Language</legend>
        <label>
          <input type="radio" name="language" checked={language === "sql"} onChange={() => setLanguage("sql")} />
          SQL
        </label>
        <label>
          <input type="radio" name="language" checked={language === "python"} onChange={() => setLanguage("python")} />
          Python
        </label>
      </fieldset>
      <label className="field">
        What does it change?
        <input autoFocus value={description} onChange={(e) => setDescription(e.target.value)} placeholder="add invoices table" required />
      </label>
      <p className="newmigration__hint">
        {kind === "versioned"
          ? "Gets the next version number, and an empty undo script beside it."
          : "Has no version: it runs again whenever its content changes."}
      </p>
      {locked ? (
        <p className="newmigration__hint">A change is running on this project. Creating is paused until it ends.</p>
      ) : (
        previewing && (
          <p className="newmigration__hint">Close the SQL preview before creating a migration: what is applied must be what was shown.</p>
        )
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="newmigration__actions">
        <button type="button" className="button button--quiet" onClick={onCancel}>
          Cancel
        </button>
        <button className="button button--primary" disabled={busy || locked || previewing}>
          Create
        </button>
      </div>
    </form>
  );
}
