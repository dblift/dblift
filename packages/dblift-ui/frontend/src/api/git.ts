import { request } from "./client";
import type { Branch, RepoStatus } from "./types";

const base = (projectId: string) => `/projects/${projectId}/git`;

// Each verb answers the repository's status after it ran.
const verb = (projectId: string, name: string, body?: unknown) =>
  request<RepoStatus>(`${base(projectId)}/${name}`, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const getRepo = (projectId: string) => request<RepoStatus>(base(projectId));

export const getBranches = (projectId: string) => request<Branch[]>(`${base(projectId)}/branches`);

export const switchBranch = (projectId: string, name: string) => verb(projectId, "switch", { name });

export const createBranch = (projectId: string, name: string) => verb(projectId, "create", { name });

export const fetchRepo = (projectId: string) => verb(projectId, "fetch");

export const pullRepo = (projectId: string) => verb(projectId, "pull");

export const pushRepo = (projectId: string) => verb(projectId, "push");

export const commitFiles = (projectId: string, paths: string[], message: string) =>
  verb(projectId, "commit", { paths, message });

/** The unified diff of a script against the last commit; "" when it is unchanged. */
export const scriptDiff = (projectId: string, name: string) =>
  request<{ diff: string }>(`/projects/${projectId}/scripts/${encodeURIComponent(name)}/diff`).then(({ diff }) => diff);
