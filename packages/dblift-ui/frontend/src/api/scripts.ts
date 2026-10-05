import { request } from "./client";
import type { Script, ScriptFile } from "./types";

const base = (projectId: string) => `/projects/${projectId}/scripts`;

export const listScripts = (projectId: string) => request<Script[]>(base(projectId));

export const readScript = (projectId: string, name: string) =>
  request<ScriptFile>(`${base(projectId)}/${encodeURIComponent(name)}`);

export const saveScript = (projectId: string, name: string, content: string) =>
  request<Script>(`${base(projectId)}/${encodeURIComponent(name)}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });

export interface NewScripts {
  kind: "versioned" | "repeatable";
  language: "sql" | "python";
  description: string;
}

export const createScripts = (projectId: string, body: NewScripts) =>
  request<{ created: string[] }>(base(projectId), { method: "POST", body: JSON.stringify(body) });
