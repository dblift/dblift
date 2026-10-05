import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { discoverFolder } from "./api/discovery";
import { listProjects, setEnvironment } from "./api/projects";
import type { Project } from "./api/types";
import AddProject from "./components/AddProject";
import ConfigForm, { type ConfigTarget } from "./components/ConfigForm";
import EmptyState from "./components/EmptyState";
import NewConfigsNotice from "./components/NewConfigsNotice";
import Sidebar from "./components/Sidebar";
import StatusView, { type StatusViewHandle } from "./components/StatusView";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

function Shell() {
  const { data: projects = [], error, isPending } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  // Set when Add project opens on a folder already: the configs a branch brought in.
  const [addFolder, setAddFolder] = useState<string | undefined>(undefined);
  const [newConfigs, setNewConfigs] = useState<{ folder: string; count: number } | null>(null);
  const [configuring, setConfiguring] = useState<ConfigTarget | null>(null);
  const selected = projects.find((p) => p.id === selectedId) ?? projects[0] ?? null;
  const client = useQueryClient();
  // Leaving the open project goes through its view, which asks first when a script has unsaved edits.
  const view = useRef<StatusViewHandle>(null);
  const leave = (action: () => void) => (view.current ? view.current.leave(action) : action());
  const select = (id: string) => {
    if (id !== selected?.id) {
      leave(() => {
        setSelectedId(id);
        setNewConfigs(null);
      });
    }
  };

  // Keep the cached list in step with the server, so the project re-opens on the
  // environment it was left on.
  const changeEnvironment = async (id: string, environment: string) => {
    const updated = await setEnvironment(id, environment);
    client.setQueryData<Project[]>(["projects"], (list) => list?.map((p) => (p.id === updated.id ? updated : p)));
  };

  // The saved project shows at once (its new environments, or the new project selected); the list is
  // then read again, and an edited project re-reads its status and scripts from the new file.
  const configSaved = (saved: Project) => {
    const edited = projects.some((p) => p.id === saved.id);
    client.setQueryData<Project[]>(["projects"], (list = []) =>
      edited ? list.map((p) => (p.id === saved.id ? saved : p)) : [...list, saved],
    );
    void client.invalidateQueries({ queryKey: ["projects"] });
    if (edited && saved.id === selected?.id) {
      view.current?.reread();
    }
    setSelectedId(saved.id);
    setConfiguring(null);
  };

  // After a switch or a pull the files are another branch's: the list and the open view are read
  // again, and configs that are not projects yet are offered.
  const followBranch = async (project: Project) => {
    void client.invalidateQueries({ queryKey: ["projects"] });
    view.current?.reread();
    try {
      const found = await discoverFolder(project.repository_path);
      const count = found.configs.filter((c) => !c.registered && c.kind !== "template" && c.problem === null).length;
      setNewConfigs(count > 0 ? { folder: project.repository_path, count } : null);
    } catch {
      // The offer is a convenience: without it, Add project still finds them.
      setNewConfigs(null);
    }
  };

  return (
    <div className="app" role="application" aria-label="DBLift UI">
      <Sidebar
        projects={projects}
        selectedId={selected?.id ?? null}
        onSelect={select}
        onAdd={() =>
          leave(() => {
            setAddFolder(undefined);
            setAdding(true);
          })
        }
        onLeave={leave}
      />
      <main className="app__main">
        {error && (
          <p className="notice notice--error" role="alert">
            Cannot reach the DBLift UI server: {error.message}. If this tab was opened from an old
            address, run <span className="mono">dblift ui</span> again and use the new one.
          </p>
        )}
        {!error && !isPending && !selected && <EmptyState />}
        {newConfigs && (
          <NewConfigsNotice
            count={newConfigs.count}
            onAdd={() =>
              leave(() => {
                setAddFolder(newConfigs.folder);
                setNewConfigs(null);
                setAdding(true);
              })
            }
            onDismiss={() => setNewConfigs(null)}
          />
        )}
        {selected && (
          <StatusView
            key={selected.id}
            ref={view}
            project={selected}
            onEnvironmentChange={(environment) => changeEnvironment(selected.id, environment)}
            onConfigure={() => setConfiguring({ kind: "edit", project: selected })}
            onMoved={() => void followBranch(selected)}
          />
        )}
      </main>
      {adding && (
        <AddProject
          projects={projects}
          initialFolder={addFolder}
          onClose={() => {
            setAdding(false);
            setAddFolder(undefined);
          }}
          onAdded={(ids) => setSelectedId(ids[0])}
          onConfigure={(target) => {
            setAdding(false);
            setAddFolder(undefined);
            setConfiguring({ kind: "create", ...target });
          }}
        />
      )}
      {configuring && <ConfigForm target={configuring} onSaved={configSaved} onClose={() => setConfiguring(null)} />}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  );
}
