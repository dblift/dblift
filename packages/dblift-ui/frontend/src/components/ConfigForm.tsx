import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";

import { createConfig, getEngines, previewConfig, readConfig, updateConfig } from "../api/configs";
import type { ConfigFormData, ConfigPreview, ConnectionForm, EngineSpec, EnvironmentForm, PasswordForm, Project } from "../api/types";
import { emptyConnection, emptyForm, ENV_DEFAULT, withEngine } from "../config/defaults";
import Dialog from "./Dialog";
import EngineLogo from "./EngineLogo";

export const PREVIEW_DELAY = 400;

const LABELS: Record<string, string> = {
  host: "Host",
  port: "Port",
  database: "Database",
  service_name: "Service name",
  account: "Account",
  warehouse: "Warehouse",
  path: "Database file",
  username: "User",
  schema: "Schema",
};
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];
// The fields that hold a long value get more of the row.
const WIDE = ["host", "account", "path"];

type Target = { kind: "create"; folder: string; migrations: string; name: string } | { kind: "edit"; project: Project };

interface Props {
  target: Target;
  onSaved: (project: Project) => void;
  onClose: () => void;
}

type TextField = Exclude<keyof ConnectionForm, "mode" | "port" | "password">;

interface ConnectionProps {
  engine: EngineSpec;
  value: ConnectionForm;
  onChange: (value: ConnectionForm) => void;
  /** An environment's connection: every field may stay empty to use the main one. */
  inherit?: ConnectionForm;
  /** The file holds a password for this connection, which the form never sees. */
  hadPassword: boolean;
}

function ConnectionFields({ engine, value, onChange, inherit, hadPassword }: ConnectionProps) {
  const name = useId();
  const set = (patch: Partial<ConnectionForm>) => onChange({ ...value, ...patch });
  const setPassword = (mode: PasswordForm["mode"]) =>
    // A value belongs to its mode: a typed password does not stay behind once another mode is chosen.
    set({ password: { mode, value: mode === "env" ? ENV_DEFAULT : "" } });
  const password = value.password;
  const hint = (field: keyof ConnectionForm) => {
    const main = inherit?.[field];
    return typeof main === "string" || typeof main === "number" ? String(main) : undefined;
  };

  return (
    <>
      {inherit && <p className="dialog__hint">Leave a field empty to use the main value.</p>}
      {value.mode === "url" ? (
        <label className="field">
          Connection URL
          <input className="mono" value={value.url} onChange={(e) => set({ url: e.target.value })} spellCheck={false} />
        </label>
      ) : (
        <div className="field-row">
          {engine.fields
            .filter((field) => field !== "password")
            .map((field) =>
              field === "port" ? (
                <label key={field} className="field field--port">
                  {LABELS.port}
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    value={value.port ?? ""}
                    placeholder={hint("port")}
                    onChange={(e) => set({ port: Number.isNaN(e.target.valueAsNumber) ? null : e.target.valueAsNumber })}
                  />
                </label>
              ) : (
                <label key={field} className={WIDE.includes(field) ? "field field--wide" : "field"}>
                  {LABELS[field] ?? field}
                  <input
                    className={field === "path" ? "mono" : undefined}
                    value={value[field as TextField]}
                    placeholder={hint(field as TextField)}
                    onChange={(e) => set({ [field]: e.target.value })}
                    spellCheck={false}
                  />
                </label>
              ),
            )}
        </div>
      )}
      {engine.fields.includes("password") && (
        <fieldset className="config__password" role="group" aria-label="Password">
          <legend>Password</legend>
          <div className="config__modes">
            {inherit && (
              <label>
                <input type="radio" name={name} checked={password.mode === "none"} onChange={() => setPassword("none")} />
                Same as main
              </label>
            )}
            <label>
              <input type="radio" name={name} checked={password.mode === "env"} onChange={() => setPassword("env")} />
              Environment variable
            </label>
            <label>
              <input type="radio" name={name} checked={password.mode === "literal"} onChange={() => setPassword("literal")} />
              Type it here
            </label>
            {hadPassword && (
              <span className="config__keep">
                <label>
                  <input type="radio" name={name} checked={password.mode === "keep"} onChange={() => setPassword("keep")} />
                  Keep the saved one
                </label>
                <span className="mono" aria-hidden="true">
                  ********
                </span>
              </span>
            )}
            {!inherit && (
              <label>
                <input type="radio" name={name} checked={password.mode === "none"} onChange={() => setPassword("none")} />
                No password
              </label>
            )}
          </div>
          {password.mode === "env" && (
            <label className="field">
              Variable name
              <input
                className="mono"
                value={password.value}
                onChange={(e) => set({ password: { mode: "env", value: e.target.value } })}
                spellCheck={false}
              />
            </label>
          )}
          {password.mode === "literal" && (
            <>
              <label className="field">
                Password value
                <input
                  type="password"
                  autoComplete="new-password"
                  value={password.value}
                  onChange={(e) => set({ password: { mode: "literal", value: e.target.value } })}
                />
              </label>
              <p className="config__warning">The password will be written in the file in clear text. Prefer a variable.</p>
            </>
          )}
        </fieldset>
      )}
    </>
  );
}

interface EditorProps {
  engines: EngineSpec[];
  initial: ConfigFormData;
  /** Set when editing: the file's revision and what the server noted while reading it. */
  document: { projectId: string; revision: string; notes: string[] } | null;
  target: Target;
  onSaved: (project: Project) => void;
  onClose: () => void;
}

interface Checked {
  key: string;
  result: ConfigPreview;
}

function Editor({ engines, initial, document: loaded, target, onSaved, onClose }: EditorProps) {
  const [form, setForm] = useState(initial);
  // One entry per environment, in the same order: a stable key, and whether the file holds its password.
  const [blocks, setBlocks] = useState(() =>
    initial.environments.map((e, index) => ({ id: index, saved: e.connection.password.mode === "keep" })),
  );
  const nextBlock = useRef(initial.environments.length);
  const [filename, setFilename] = useState("dblift.yaml");
  const [name, setName] = useState(target.kind === "create" ? target.name : "");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const sequence = useRef(0);
  const formRef = useRef<HTMLFormElement>(null);
  const mainHadPassword = initial.connection.password.mode === "keep";
  const projectId = loaded?.projectId;
  const engine = engines.find((e) => e.id === form.engine) ?? engines[0];
  const key = JSON.stringify(form);

  // Creating starts at the engine choice; editing starts at the connection.
  const editing = loaded !== null;
  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>(editing ? ".config__connection input" : "input[type=radio]:checked")?.focus();
  }, [editing]);

  // The loader checks the form once typing pauses; only the answer to the latest request is kept.
  useEffect(() => {
    const timer = setTimeout(() => {
      const current = ++sequence.current;
      const keep = (result: ConfigPreview) => {
        if (current === sequence.current) {
          setChecked({ key, result });
        }
      };
      previewConfig(form, projectId).then(keep, (failure: Error) => keep({ yaml: "", problems: [failure.message], warnings: [] }));
    }, PREVIEW_DELAY);
    return () => clearTimeout(timer);
    // `key` stands for `form`: a new object with the same content asks nothing new.
  }, [key, projectId]);

  // An answer that arrives after the dialog closed is dropped.
  useEffect(
    () => () => {
      sequence.current += 1;
    },
    [],
  );

  const current = checked !== null && checked.key === key;
  const result = checked?.result ?? null;
  const named = target.kind === "edit" || (filename.trim() !== "" && name.trim() !== "");
  const canSave = current && result !== null && result.problems.length === 0 && named && !saving;

  const update = (patch: Partial<ConfigFormData>) => setForm({ ...form, ...patch });
  const setEnvironment = (index: number, patch: Partial<EnvironmentForm>) =>
    update({ environments: form.environments.map((e, i) => (i === index ? { ...e, ...patch } : e)) });

  const addEnvironment = () => {
    update({ environments: [...form.environments, { name: "", connection: emptyConnection(engine, true) }] });
    setBlocks([...blocks, { id: nextBlock.current++, saved: false }]);
  };

  const removeEnvironment = (index: number) => {
    update({ environments: form.environments.filter((_, i) => i !== index) });
    setBlocks(blocks.filter((_, i) => i !== index));
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) {
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const project =
        target.kind === "create"
          ? await createConfig(target.folder, filename.trim(), name.trim(), form)
          : await updateConfig(target.project.id, form, loaded!.revision);
      onSaved(project);
    } catch (failure) {
      setSaveError((failure as Error).message);
      setSaving(false);
    }
  };

  const levels = LEVELS.includes(form.log_level) ? LEVELS : [form.log_level, ...LEVELS];

  return (
    <div className="config">
      <form ref={formRef} className="config__form" onSubmit={(e) => void save(e)}>
        {loaded?.notes.map((note) => (
          <p key={note} className="notice">
            {note}
          </p>
        ))}

        <fieldset className="config__section" role="radiogroup" aria-label="Engine">
          <legend>Engine</legend>
          <div className="engine-picker">
            {engines.map((spec) => (
              <label key={spec.id} className="engine-option">
                <input
                  type="radio"
                  name="engine"
                  className="visually-hidden"
                  aria-label={spec.label}
                  checked={form.engine === spec.id}
                  onChange={() => setForm(withEngine(form, spec))}
                />
                <EngineLogo engine={spec.id} size={20} />
                <span>{spec.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="config__section config__connection">
          <legend>Connection</legend>
          <ConnectionFields
            engine={engine}
            value={form.connection}
            onChange={(connection) => update({ connection })}
            hadPassword={mainHadPassword}
          />
        </fieldset>

        <fieldset className="config__section">
          <legend>Migrations</legend>
          <label className="field">
            Migrations folder
            <input
              className="mono"
              value={form.migrations_directory}
              onChange={(e) => update({ migrations_directory: e.target.value })}
              spellCheck={false}
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={form.recursive} onChange={(e) => update({ recursive: e.target.checked })} />
            Include sub-folders
          </label>
        </fieldset>

        <fieldset className="config__section">
          <legend>Options</legend>
          <label className="field field--level">
            Log level
            <select value={form.log_level} onChange={(e) => update({ log_level: e.target.value })}>
              {levels.map((level) => (
                <option key={level}>{level}</option>
              ))}
            </select>
          </label>
          <label className="check">
            <input type="checkbox" checked={form.strict_mode} onChange={(e) => update({ strict_mode: e.target.checked })} />
            Strict mode
          </label>
          <label className="check">
            <input type="checkbox" checked={form.clean_disabled} onChange={(e) => update({ clean_disabled: e.target.checked })} />
            Protect against clean
          </label>
        </fieldset>

        <fieldset className="config__section">
          <legend>Environments</legend>
          {form.environments.map((environment, index) => (
            <fieldset key={blocks[index].id} className="config__environment" role="group" aria-label={`Environment ${index + 1}`}>
              <legend>Environment {index + 1}</legend>
              <div className="config__environment-head">
                <label className="field">
                  Name
                  <input
                    className="mono"
                    value={environment.name}
                    onChange={(e) => setEnvironment(index, { name: e.target.value })}
                    placeholder="staging"
                    spellCheck={false}
                  />
                </label>
                <button type="button" className="button button--quiet" onClick={() => removeEnvironment(index)}>
                  Remove
                </button>
              </div>
              <ConnectionFields
                engine={engine}
                value={environment.connection}
                onChange={(connection) => setEnvironment(index, { connection })}
                inherit={form.connection}
                hadPassword={blocks[index].saved}
              />
            </fieldset>
          ))}
          <div>
            <button type="button" className="button" onClick={addEnvironment}>
              Add environment
            </button>
          </div>
        </fieldset>

        {target.kind === "create" && (
          <fieldset className="config__section">
            <legend>Save as</legend>
            <p className="dialog__hint">
              In <span className="mono">{target.folder}</span>
            </p>
            <div className="field-row">
              <label className="field">
                File name
                <input className="mono" value={filename} onChange={(e) => setFilename(e.target.value)} spellCheck={false} />
              </label>
              <label className="field">
                Project name
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            </div>
          </fieldset>
        )}

        {saveError && (
          <p className="error-text" role="alert">
            {saveError}
          </p>
        )}
        <div className="dialog__actions">
          <button type="button" className="button button--quiet" onClick={onClose}>
            Cancel
          </button>
          <button className="button button--primary" disabled={!canSave}>
            {target.kind === "create" ? "Create" : "Save"}
          </button>
        </div>
      </form>

      <aside className="config__preview" aria-label="Preview">
        <div className="config__preview-head">
          <h3>Preview</h3>
          <span className="config__status">{current ? (result?.problems.length ? "Needs changes" : "Checked") : "Checking…"}</span>
        </div>
        {result?.problems.length ? (
          <ul className="config__problems" role="alert">
            {result.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
        {result?.warnings.length ? (
          <ul className="config__warnings">
            {result.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
        {result?.yaml ? <pre className="mono">{result.yaml}</pre> : null}
      </aside>
    </div>
  );
}

export default function ConfigForm({ target, onSaved, onClose }: Props) {
  const editing = target.kind === "edit" ? target.project : null;
  const engines = useQuery({ queryKey: ["config-engines"], queryFn: getEngines, staleTime: Infinity });
  const stored = useQuery({
    queryKey: ["config", editing?.id ?? ""],
    queryFn: () => readConfig(editing!.id),
    enabled: editing !== null,
    // The form is read once per opening and not kept after the dialog closes.
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const failure = engines.error ?? stored.error;
  const ready = engines.data !== undefined && (editing === null || stored.data !== undefined);

  // A new configuration opens on the form: the engine list is local and arrives at once.
  if (!editing && !ready && !failure) {
    return null;
  }

  let body;
  if (ready) {
    const list = engines.data!;
    body = (
      <Editor
        engines={list}
        initial={editing ? stored.data!.form : emptyForm(list[0], target.kind === "create" ? target.migrations : "")}
        document={editing ? { projectId: editing.id, revision: stored.data!.revision, notes: stored.data!.notes } : null}
        target={target}
        onSaved={onSaved}
        onClose={onClose}
      />
    );
  } else if (failure) {
    body = (
      <div className="dialog__body">
        <p className="error-text" role="alert">
          {failure.message}
        </p>
      </div>
    );
  } else {
    body = (
      <p className="dialog__body dialog__working" aria-live="polite">
        Reading the configuration…
      </p>
    );
  }

  return (
    <Dialog wide title={editing ? `Configuration of ${editing.name}` : "New configuration"} onClose={onClose}>
      {body}
    </Dialog>
  );
}
