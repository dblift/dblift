import { type FormEvent, useEffect, useRef, useState } from "react";

type Simple = "undo" | "validate" | "repair" | "baseline";
type Asking = "undo" | "repair" | "baseline";

interface Props {
  counts: { applied: number; pending: number; failed: number };
  hasVersion: boolean;
  busy: boolean;
  onMigrate: () => void;
  onCommand: (command: Simple, params?: Record<string, unknown>) => void;
  /** Shown first when given: opens the guided new change. */
  onNewChange?: () => void;
  /** Shown when given: starts a new migration file. */
  onNew?: () => void;
}

export default function CommandBar({ counts, hasVersion, busy, onMigrate, onCommand, onNewChange, onNew }: Props) {
  const [confirming, setConfirming] = useState<Asking | null>(null);
  const [version, setVersion] = useState("");
  const [description, setDescription] = useState("");
  const canBaseline = counts.applied === 0 && !hasVersion;

  // Backing out of a question puts focus back on the button that asked it.
  const triggers = useRef<Partial<Record<Asking, HTMLButtonElement | null>>>({});
  const returnFocus = useRef<Asking | null>(null);
  useEffect(() => {
    if (confirming === null && returnFocus.current) {
      triggers.current[returnFocus.current]?.focus();
      returnFocus.current = null;
    }
  }, [confirming]);

  const cancel = () => {
    returnFocus.current = confirming;
    setConfirming(null);
  };
  const confirm = (command: "undo" | "repair") => {
    setConfirming(null);
    onCommand(command);
  };
  const recordBaseline = (event: FormEvent) => {
    event.preventDefault();
    setConfirming(null);
    onCommand("baseline", { version, description });
  };

  // Each view has its own key so React mounts fresh buttons: a reused node would
  // keep the focus of the button just clicked and hand it to "Confirm".
  if (confirming === "baseline") {
    return (
      <form key="baseline" className="commands commands--form" onSubmit={recordBaseline}>
        <label className="field">
          Baseline version
          <input
            className="mono"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="1.0.0"
            required
            autoFocus
          />
        </label>
        <label className="field">
          Description
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="existing schema" />
        </label>
        <p className="commands__hint">
          Marks this database as already at that version. Migrations up to it are not run.
        </p>
        <button type="button" className="button button--quiet" onClick={cancel}>
          Cancel
        </button>
        <button className="button button--primary" disabled={busy}>
          Record baseline
        </button>
      </form>
    );
  }

  if (confirming) {
    const words = confirming === "undo" ? "Confirm undo" : "Confirm repair";
    const hint =
      confirming === "undo"
        ? "Runs the undo script of the migration applied last."
        : "Removes the failed entries from the history so they can be run again.";
    return (
      <div key={confirming} className="commands">
        <p className="commands__hint" id="command-hint">
          {hint}
        </p>
        <button className="button button--quiet" onClick={cancel} autoFocus>
          Cancel
        </button>
        <button
          className="button button--danger"
          aria-describedby="command-hint"
          disabled={busy}
          onClick={() => confirm(confirming)}
        >
          {words}
        </button>
      </div>
    );
  }

  return (
    <div key="bar" className="commands">
      {onNewChange && (
        <button className="button" disabled={busy} onClick={onNewChange}>
          New change
        </button>
      )}
      {onNew && (
        <button className="button" disabled={busy} onClick={onNew}>
          New migration
        </button>
      )}
      {canBaseline && (
        <button
          ref={(node) => {
            triggers.current.baseline = node;
          }}
          className="button"
          disabled={busy}
          onClick={() => setConfirming("baseline")}
        >
          Baseline…
        </button>
      )}
      <button className="button" disabled={busy} onClick={() => onCommand("validate")}>
        Validate
      </button>
      <button
        ref={(node) => {
          triggers.current.undo = node;
        }}
        className="button"
        disabled={busy || counts.applied === 0}
        onClick={() => setConfirming("undo")}
      >
        Undo last migration
      </button>
      {counts.failed > 0 && (
        <button
          ref={(node) => {
            triggers.current.repair = node;
          }}
          className="button button--danger"
          disabled={busy}
          onClick={() => setConfirming("repair")}
        >
          Repair
        </button>
      )}
      <button
        className="button button--primary"
        disabled={busy || counts.pending === 0 || counts.failed > 0}
        onClick={onMigrate}
      >
        Migrate
      </button>
    </div>
  );
}
