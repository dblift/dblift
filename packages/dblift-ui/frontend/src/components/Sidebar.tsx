import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { addProject, removeProject } from "../api/projects";
import type { Project } from "../api/types";
import EngineLogo from "./EngineLogo";

interface Props {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function Sidebar({ projects, selectedId, onSelect }: Props) {
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [configPath, setConfigPath] = useState("");
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
            <button
              className="button button--quiet"
              aria-label={`Remove ${project.name}`}
              onClick={() => remove.mutate(project.id)}
            >
              ✕
            </button>
          </li>
        ))}
      </ul>

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
