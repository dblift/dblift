import { request } from "./client";
import type { Defaults, Discovery } from "./types";

export const getDefaults = () => request<Defaults>("/defaults");

export const discoverFolder = (path: string) =>
  request<Discovery>("/discover", { method: "POST", body: JSON.stringify({ path }) });

export const cloneRepository = (url: string, parent: string) =>
  request<{ path: string }>("/clone", { method: "POST", body: JSON.stringify({ url, parent }) });
