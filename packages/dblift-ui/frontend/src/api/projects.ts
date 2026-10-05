import { request } from "./client";
import type { Project } from "./types";

export const listProjects = () => request<Project[]>("/projects");

export const addProject = (name: string, configPath: string) =>
  request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name, config_path: configPath }),
  });

export const removeProject = (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" });

export const setEnvironment = (id: string, environment: string) =>
  request<Project>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ last_environment: environment }),
  });
