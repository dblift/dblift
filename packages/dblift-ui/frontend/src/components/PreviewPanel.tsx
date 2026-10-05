import type { SqlPreview } from "../api/types";

interface Props {
  preview: SqlPreview[];
  busy: boolean;
  onApply: () => void;
  onCancel: () => void;
}

export default function PreviewPanel({ preview, busy, onApply, onCancel }: Props) {
  const count = preview.length;
  return (
    <section className="preview panel rise" aria-label="SQL to be applied">
      <header className="preview__head">
        <h2>This is what will run</h2>
        <div className="preview__actions">
          <button className="button button--quiet" onClick={onCancel} autoFocus>
            Cancel
          </button>
          <button className="button button--primary" disabled={busy || count === 0} onClick={onApply}>
            Apply {count} {count === 1 ? "migration" : "migrations"}
          </button>
        </div>
      </header>
      <div className="preview__body">
        {preview.map((entry) => (
          <div key={entry.script} className="preview__script">
            <p className="mono preview__name">{entry.script}</p>
            <pre className="mono preview__sql">{entry.statements.join("\n")}</pre>
          </div>
        ))}
        {count === 0 && <p>Nothing to apply.</p>}
      </div>
    </section>
  );
}
