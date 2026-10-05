import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { listProjects, setEnvironment } from "./api/projects";
import type { Project } from "./api/types";
import EmptyState from "./components/EmptyState";
import Sidebar from "./components/Sidebar";
import StatusView, { type StatusViewHandle } from "./components/StatusView";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

function Shell() {
  const { data: projects = [], error, isPending } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = projects.find((p) => p.id === selectedId) ?? projects[0] ?? null;
  const client = useQueryClient();
  // Leaving the open project goes through its view, which asks first when a script has unsaved edits.
  const view = useRef<StatusViewHandle>(null);
  const leave = (action: () => void) => (view.current ? view.current.leave(action) : action());
  const select = (id: string) => {
    if (id !== selected?.id) {
      leave(() => setSelectedId(id));
    }
  };

  // Keep the cached list in step with the server, so the project re-opens on the
  // environment it was left on.
  const changeEnvironment = async (id: string, environment: string) => {
    const updated = await setEnvironment(id, environment);
    client.setQueryData<Project[]>(["projects"], (list) => list?.map((p) => (p.id === updated.id ? updated : p)));
  };

  return (
    <div className="app" role="application" aria-label="DBLift UI">
      <Sidebar projects={projects} selectedId={selected?.id ?? null} onSelect={select} onLeave={leave} />
      <main className="app__main">
        {error && (
          <p className="notice notice--error" role="alert">
            Cannot reach the DBLift UI server: {error.message}. If this tab was opened from an old
            address, run <span className="mono">dblift ui</span> again and use the new one.
          </p>
        )}
        {!error && !isPending && !selected && <EmptyState />}
        {selected && (
          <StatusView
            key={selected.id}
            ref={view}
            project={selected}
            onEnvironmentChange={(environment) => changeEnvironment(selected.id, environment)}
          />
        )}
      </main>
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
