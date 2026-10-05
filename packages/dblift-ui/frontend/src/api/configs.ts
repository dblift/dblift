import { request } from "./client";
import type { ConfigDocument, ConfigFormData, ConfigPreview, EngineSpec, Project } from "./types";

export const getEngines = () => request<EngineSpec[]>("/config/engines");

export const previewConfig = (form: ConfigFormData, projectId = "") =>
  request<ConfigPreview>("/config/preview", { method: "POST", body: JSON.stringify({ form, project_id: projectId }) });

export const createConfig = (folder: string, filename: string, name: string, form: ConfigFormData) =>
  request<Project>("/config", { method: "POST", body: JSON.stringify({ folder, filename, name, form }) });

export const readConfig = (projectId: string) => request<ConfigDocument>(`/projects/${projectId}/config`);

export const updateConfig = (projectId: string, form: ConfigFormData, revision: string) =>
  request<Project>(`/projects/${projectId}/config`, { method: "PUT", body: JSON.stringify({ form, revision }) });
