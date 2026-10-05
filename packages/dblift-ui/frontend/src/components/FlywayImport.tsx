import { useEffect, useId, useRef, useState } from "react";

import type { CommandRun } from "../commands/useCommand";

interface Props {
  table: string;
  busy: boolean;
  run: CommandRun | null;
  onPreview: () => void;
  onImport: () => void;
}

/** Offered while a Flyway project's history has not been taken over. */
export default function FlywayImport({ table, busy, run, onPreview, onImport }: Props) {
  const title = useId();
  const hint = useId();
  const [asking, setAsking] = useState(false);
  const mine = run && run.command.startsWith("flyway_") && run.phase !== "running" ? run : null;

  // Backing out of the question puts focus back on the button that asked it.
  const opener = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (!asking && returnFocus.current) {
      opener.current?.focus();
      returnFocus.current = false;
    }
  }, [asking]);

  const cancel = () => {
    returnFocus.current = true;
    setAsking(false);
  };

  return (
    <section className="panel flyway rise" aria-labelledby={title}>
      <h2 id={title}>Flyway history</h2>
      <p>
        This project comes from Flyway. Import its history (table <span className="mono">{table}</span>) so that what
        Flyway already applied is not offered again. Import it before migrating: otherwise the migrations Flyway
        already applied would be run again. Nothing is removed from the Flyway table.
      </p>
      {mine?.error && (
        <p className="error-text" role="alert">
          {mine.error}
        </p>
      )}
      {mine && !mine.error && mine.result?.message && <p role="status">{mine.result.message}</p>}
      {/* Each view has its own key so React mounts fresh buttons, as in the command bar. */}
      {asking ? (
        <div
          key="asking"
          className="flyway__actions"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              cancel();
            }
          }}
        >
          <span className="flyway__question" id={hint}>
            Import the Flyway history into this database?
          </span>
          <button className="button button--quiet" autoFocus onClick={cancel}>
            Cancel
          </button>
          <button
            className="button button--primary"
            aria-describedby={hint}
            disabled={busy}
            onClick={() => {
              setAsking(false);
              onImport();
            }}
          >
            Import
          </button>
        </div>
      ) : (
        <div key="offer" className="flyway__actions">
          <button className="button" disabled={busy} onClick={onPreview}>
            Preview the import
          </button>
          <button ref={opener} className="button" disabled={busy} onClick={() => setAsking(true)}>
            Import history
          </button>
        </div>
      )}
    </section>
  );
}
