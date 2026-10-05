import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { cloneRepository, discoverFolder, getDefaults } from "../api/discovery";
import { addProject } from "../api/projects";
import type { Discovery, FoundConfig, Project } from "../api/types";
import { defaultNames } from "../projects/naming";

interface Props {
  projects: Project[];
  onAdded: (ids: string[]) => void;
  onClose: () => void;
}

type Source = "folder" | "clone";

const KIND_NOTE: Record<FoundConfig["kind"], string | null> = {
  named: null,
  content: "detected by its content",
  template: "template or example",
};

const FOCUSABLE = "button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex='-1'])";

const usable = (config: FoundConfig) => !config.registered && config.problem === null;

export default function AddProject({ projects, onAdded, onClose }: Props) {
  const queryClient = useQueryClient();
  const { data: defaults } = useQuery({ queryKey: ["defaults"], queryFn: getDefaults });
  const [source, setSource] = useState<Source>("folder");
  const [folder, setFolder] = useState("");
  const [address, setAddress] = useState("");
  const [parent, setParent] = useState<string | null>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<Discovery | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  // Names the user typed; the others follow the selection.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [added, setAdded] = useState<string[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const first = useRef<HTMLInputElement>(null);

  // The first field takes focus on open; focus goes back where it was on close.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    first.current?.focus();
    return () => opener?.focus();
  }, []);

  // Escape closes; Tab and Shift+Tab cycle through the dialog's controls only.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !box.current) {
        return;
      }
      const controls = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (controls.length === 0) {
        return;
      }
      const head = controls[0];
      const tail = controls[controls.length - 1];
      const inside = box.current.contains(document.activeElement);
      if (event.shiftKey && (!inside || document.activeElement === head)) {
        event.preventDefault();
        tail.focus();
      } else if (!event.shiftKey && (!inside || document.activeElement === tail)) {
        event.preventDefault();
        head.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const cloneParent = parent ?? defaults?.clone_parent ?? "";
  const repositories = [...new Set(projects.map((p) => p.repository_path))].sort();
  const names = found ? { ...defaultNames(found, selected), ...typed } : typed;

  const scan = async (path: string) => {
    setWorking("Looking for configs…");
    setError(null);
    try {
      const discovery = await discoverFolder(path);
      setFound(discovery);
      setTyped({});
      setFailures({});
      setAdded([]);
      setSelected(discovery.configs.filter((c) => c.kind !== "template" && usable(c)).map((c) => c.path));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setWorking(null);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (source === "folder") {
      await scan(folder);
      return;
    }
    setWorking("Cloning the repository…");
    setError(null);
    try {
      const { path } = await cloneRepository(address, cloneParent);
      await scan(path);
    } catch (failure) {
      setError((failure as Error).message);
      setWorking(null);
    }
  };

  const toggle = (path: string) => {
    if (!found) {
      return;
    }
    const next = selected.includes(path) ? selected.filter((p) => p !== path) : [...selected, path];
    // Keep the order of the list.
    setSelected(found.configs.map((c) => c.path).filter((p) => next.includes(p)));
  };

  const addSelected = async () => {
    if (!found) {
      return;
    }
    setWorking("Adding…");
    const ids: string[] = [];
    const done: string[] = [];
    const failed: Record<string, string> = {};
    for (const path of selected) {
      try {
        const project = await addProject(names[path] ?? found.name, `${found.root}/${path}`);
        ids.push(project.id);
        done.push(path);
      } catch (failure) {
        failed[path] = (failure as Error).message;
      }
    }
    setWorking(null);
    if (ids.length) {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      onAdded(ids);
    }
    if (Object.keys(failed).length === 0) {
      onClose();
      return;
    }
    // The ones left keep the names they were tried with, so a retry does not rename them.
    setTyped(Object.fromEntries(Object.keys(failed).map((path) => [path, names[path] ?? found.name])));
    setFailures(failed);
    setAdded((previous) => [...previous, ...done]);
    setSelected(selected.filter((path) => path in failed));
  };

  const count = selected.length;

  return (
    <div className="dialog-scrim">
      <div ref={box} className="dialog panel" role="dialog" aria-modal="true" aria-labelledby="add-project-title">
        <header className="dialog__head">
          <h2 id="add-project-title">Add project</h2>
          <button className="button button--quiet" onClick={onClose}>
            Close
          </button>
        </header>

        {!found && (
          <form className="dialog__body" onSubmit={(e) => void submit(e)}>
            <fieldset className="choice">
              <legend>Where is it?</legend>
              <label>
                <input type="radio" name="source" checked={source === "folder"} onChange={() => setSource("folder")} />
                Open a folder
              </label>
              <label>
                <input type="radio" name="source" checked={source === "clone"} onChange={() => setSource("clone")} />
                Clone a repository
              </label>
            </fieldset>

            {source === "folder" ? (
              <label className="field">
                Folder path
                <input
                  ref={first}
                  className="mono"
                  value={folder}
                  onChange={(e) => setFolder(e.target.value)}
                  placeholder="/path/to/your/repository"
                  required
                />
              </label>
            ) : (
              <>
                <label className="field">
                  Repository address
                  <input
                    className="mono"
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="git@github.com:acme/shop-api.git"
                    required
                  />
                </label>
                <label className="field">
                  Clone into
                  <input className="mono" value={cloneParent} onChange={(e) => setParent(e.target.value)} required />
                </label>
                <p className="dialog__hint">
                  {defaults && !defaults.git
                    ? "git is not installed on this machine, so a repository cannot be cloned from here."
                    : "The repository lands in a sub-folder named after it. Your own git credentials are used; nothing is asked here."}
                </p>
              </>
            )}

            {error && (
              <p className="error-text" role="alert">
                {error}
              </p>
            )}
            {working && (
              <p className="dialog__working" aria-live="polite">
                {working}
              </p>
            )}

            <div className="dialog__actions">
              <button className="button button--primary" disabled={working !== null || (source === "clone" && defaults?.git === false)}>
                {source === "folder" ? "Look for configs" : "Clone and look for configs"}
              </button>
            </div>

            {source === "folder" && repositories.length > 0 && (
              <div className="shortcuts" role="group" aria-label="Scan again">
                <p className="shortcuts__title">Scan again</p>
                {repositories.map((path) => (
                  <button
                    key={path}
                    type="button"
                    className="button button--quiet mono"
                    disabled={working !== null}
                    onClick={() => {
                      setFolder(path);
                      void scan(path);
                    }}
                  >
                    {path}
                  </button>
                ))}
              </div>
            )}
          </form>
        )}

        {found && (
          <div className="dialog__body">
            <p className="found__where">
              <span className="mono">{found.root}</span>
              {found.branch && <span className="chip mono">{found.branch}</span>}
            </p>
            {found.truncated && (
              <p className="notice">This folder holds too many files to scan entirely; some configs may be missing from the list.</p>
            )}

            {found.configs.length === 0 ? (
              <p>No config file was found in this folder.</p>
            ) : (
              <ul className="found__list">
                {found.configs.map((config) => {
                  const done = added.includes(config.path);
                  const disabled = !usable(config) || done;
                  const checked = selected.includes(config.path);
                  return (
                    <li key={config.path} className="found__item">
                      <label className="found__pick">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={() => toggle(config.path)}
                          aria-label={config.path}
                        />
                        <span className="mono">{config.path}</span>
                      </label>
                      <span className="found__notes">
                        {KIND_NOTE[config.kind] && <span className="chip">{KIND_NOTE[config.kind]}</span>}
                        {(config.registered || done) && <span className="chip">{done ? "added" : "already added"}</span>}
                        {config.problem && <span className="error-text">{config.problem}</span>}
                      </span>
                      {checked && (
                        <input
                          className="found__name"
                          aria-label={`Name for ${config.path}`}
                          value={names[config.path] ?? ""}
                          onChange={(e) => setTyped({ ...typed, [config.path]: e.target.value })}
                        />
                      )}
                      {failures[config.path] && (
                        <p className="error-text" role="alert">
                          {failures[config.path]}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}

            {found.flyway.length > 0 && (
              <section className="found__other">
                <h3>Flyway projects</h3>
                <ul>
                  {found.flyway.map((path) => (
                    <li key={path} className="mono">
                      {path}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {found.script_folders.length > 0 && (
              <section className="found__other">
                <h3>Migration folders no config points at</h3>
                <ul>
                  {found.script_folders.map((path) => (
                    <li key={path} className="mono">
                      {path}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {working && (
              <p className="dialog__working" aria-live="polite">
                {working}
              </p>
            )}
            <div className="dialog__actions">
              <button className="button button--quiet" disabled={working !== null} onClick={() => setFound(null)}>
                Back
              </button>
              {found.configs.length > 0 && (
                <button className="button button--primary" disabled={count === 0 || working !== null} onClick={() => void addSelected()}>
                  Add {count} {count === 1 ? "project" : "projects"}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
