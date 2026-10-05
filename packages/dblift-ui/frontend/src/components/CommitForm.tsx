import { type FormEvent, type ReactNode, useId, useState } from "react";

import type { ChangedFile } from "../api/types";

export interface CommitFormProps {
  files: ChangedFile[];
  /** Paths ticked when the form opens. */
  preselected: string[];
  /** True while the commit runs. */
  busy: boolean;
  /** Why git refused the commit; the form keeps the selection and the message. */
  error: string | null;
  /** The status listed only part of the changed files. */
  truncated?: boolean;
  onCommit: (paths: string[], message: string) => void;
}

interface Props extends CommitFormProps {
  className: string;
  /** The message the form opens with. */
  message?: string;
  /** Buttons placed before the commit button. */
  actions?: ReactNode;
}

// A conflict is resolved with the user's own git tool: the interface never merges.
const committable = (file: ChangedFile) => file.state !== "conflicted";

/** The changed files to tick, and the message: the commit dialog's body, shared with the new-change wizard. */
export default function CommitForm({ files, preselected, busy, error, truncated = false, onCommit, className, message: initial = "", actions }: Props) {
  const hint = useId();
  const [selected, setSelected] = useState<string[]>(() =>
    files.filter((f) => committable(f) && preselected.includes(f.path)).map((f) => f.path),
  );
  const [message, setMessage] = useState(initial);

  // Keep the order of the list.
  const select = (paths: string[]) => setSelected(files.map((f) => f.path).filter((p) => paths.includes(p)));
  const toggle = (path: string) => select(selected.includes(path) ? selected.filter((p) => p !== path) : [...selected, path]);
  const count = selected.length;
  const ready = count > 0 && message.trim() !== "" && !busy;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (ready) {
      onCommit(selected, message);
    }
  };

  return (
    <form className={className} onSubmit={submit}>
      {truncated && (
        <p className="notice">The list is incomplete: this repository has more changed files than can be shown here.</p>
      )}
      <div className="commit__select">
        <span className="commit__count">
          {files.length} changed {files.length === 1 ? "file" : "files"}
        </span>
        <button type="button" className="button button--quiet" onClick={() => select(files.filter(committable).map((f) => f.path))}>
          Select all
        </button>
        <button type="button" className="button button--quiet" onClick={() => select([])}>
          Select none
        </button>
      </div>
      <ul className="commit__files">
        {files.map((file) => (
          <li key={file.path} className="commit__file">
            <label className="commit__pick">
              <input
                type="checkbox"
                aria-label={file.path}
                checked={selected.includes(file.path)}
                disabled={!committable(file)}
                onChange={() => toggle(file.path)}
              />
              <span className="mono">{file.path}</span>
            </label>
            <span className={file.state === "conflicted" ? "chip commit__state commit__state--conflicted" : "chip commit__state"}>
              {file.state}
            </span>
            {!committable(file) && <span className="commit__note">resolve with your own tool</span>}
          </li>
        ))}
      </ul>

      <label className="field">
        Message
        <textarea
          data-autofocus
          className="commit__message"
          rows={4}
          required
          aria-describedby={hint}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
      </label>
      <p className="dialog__hint" id={hint}>
        The first line is the summary; leave a blank line before any detail.
      </p>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="dialog__actions">
        {actions}
        <button className="button button--primary" disabled={!ready}>
          Commit {count} {count === 1 ? "file" : "files"}
        </button>
      </div>
    </form>
  );
}
