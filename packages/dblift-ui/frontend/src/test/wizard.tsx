import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { type JSX, useState } from "react";
import { vi } from "vitest";

import type { Project, RepoStatus } from "../api/types";
import { START, type StepProps, type WizardContext, type WizardData } from "../wizard/steps";

export const project: Project = {
  id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "", environments: [], engine: "sqlite",
  error: null, missing: false, repository: "shop", repository_path: "/work/shop", flyway_table: null,
};

export const onMain: RepoStatus = {
  repository: true, root: "/work/shop", branch: "main", detached: false, upstream: "origin/main", ahead: 0, behind: 0, files: [], truncated: false,
};

export const V = "V1_0_2__add_invoices.sql";
export const U = "U1_0_2__add_invoices.sql";

interface Options {
  data?: Partial<WizardData>;
  repo?: RepoStatus;
  last?: boolean;
}

/** Render one step on its own, with a context that follows its updates as the shell's does. */
export function renderStep(Step: (props: StepProps) => JSX.Element, { data = {}, repo, last = false }: Options = {}) {
  const onNext = vi.fn();
  const onBack = vi.fn();
  const changed = vi.fn();
  const latest: { context: WizardContext | null } = { context: null };

  function Harness() {
    const [state, setState] = useState<WizardData>({ ...START, ...data });
    const context: WizardContext = {
      ...state, project, repo, changed,
      update: (partial) => setState((current) => ({ ...current, ...(typeof partial === "function" ? partial(current) : partial) })),
    };
    latest.context = context;
    return <Step context={context} onNext={onNext} onBack={onBack} last={last} />;
  }

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (repo) {
    client.setQueryData(["git", project.id], repo);
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  return { view, onNext, onBack, changed, context: () => latest.context! };
}
