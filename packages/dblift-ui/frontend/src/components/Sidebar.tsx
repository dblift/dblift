import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { addProject, removeProject } from "../api/projects";
import type { Project } from "../api/types";
import EngineLogo from "./EngineLogo";

interface Props {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Runs an action that closes the open project, once the open project agrees to be left. */
  onLeave?: (action: () => void) => void;
}

export default function Sidebar({ projects, selectedId, onSelect, onLeave = (action) => action() }: Props) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [configPath, setConfigPath] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const confirmBox = useRef<HTMLSpanElement>(null);
  const refreshList = () => queryClient.invalidateQueries({ queryKey: ["projects"] });

  const add = useMutation({
    mutationFn: () => addProject(name, configPath),
    onSuccess: async (project) => {
      await refreshList();
      setAdding(false);
      setName("");
      setConfigPath("");
      onSelect(project.id);
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => removeProject(id), onSuccess: refreshList });

  // A pending confirmation is dropped as soon as the user clicks anywhere else.
  useEffect(() => {
    if (!confirming) {
      return;
    }
    const dismiss = (event: PointerEvent) => {
      if (!confirmBox.current?.contains(event.target as Node)) {
        setConfirming(null);
      }
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [confirming]);

  const confirmRemoval = (id: string) => {
    setConfirming(null);
    if (id === selectedId) {
      onLeave(() => remove.mutate(id));
    } else {
      remove.mutate(id);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };

  return (
    <aside className="sidebar">
      <p className="sidebar__brand">
        DBLift <span className="mono">UI</span>
      </p>
      <h2 className="sidebar__title">Projects</h2>
      <ul className="sidebar__list">
        {projects.map((project, index) => (
          <li key={project.id} className="sidebar__item rise" style={{ "--order": index } as React.CSSProperties}>
            <button
              className="sidebar__project"
              aria-current={project.id === selectedId ? "true" : undefined}
              onClick={() => onSelect(project.id)}
            >
              <EngineLogo engine={project.engine} />
              <span className="sidebar__project-text">
                <strong>{project.name}</strong>
                <span className="mono">{project.error ? "config problem" : project.engine || "unknown engine"}</span>
              </span>
            </button>
            {confirming === project.id ? (
              <span className="sidebar__confirm" ref={confirmBox}>
                <span className="visually-hidden" id={`remove-note-${project.id}`}>
                  Removes {project.name} only from this list. No file is deleted.
                </span>
                <button
                  className="button button--danger"
                  aria-describedby={`remove-note-${project.id}`}
                  title="Remove from this list. No file is deleted."
                  onClick={() => confirmRemoval(project.id)}
                >
                  Remove
                </button>
                <button className="button button--quiet" onClick={() => setConfirming(null)} autoFocus>
                  Cancel
                </button>
              </span>
            ) : (
              <button
                className="button button--quiet"
                aria-label={`Remove ${project.name}`}
                title="Remove from this list. No file is deleted."
                onClick={() => setConfirming(project.id)}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
      {remove.isError && (
        <p className="error-text sidebar__error" role="alert">
          Could not remove the project: {remove.error.message}
        </p>
      )}

      {adding ? (
        <form className="sidebar__form" onSubmit={submit}>
          <label className="field">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label className="field">
            Config file path
            <input
              className="mono"
              value={configPath}
              onChange={(e) => setConfigPath(e.target.value)}
              placeholder="/path/to/dblift.yaml"
              required
            />
          </label>
          {add.isError && (
            <p className="error-text" role="alert">
              {add.error.message}
            </p>
          )}
          <div className="sidebar__form-actions">
            <button type="button" className="button button--quiet" onClick={() => setAdding(false)}>
              Cancel
            </button>
            <button className="button button--primary" disabled={add.isPending}>
              Add
            </button>
          </div>
        </form>
      ) : (
        <button className="button sidebar__add" onClick={() => setAdding(true)}>
          Add project
        </button>
      )}
    </aside>
  );
}
