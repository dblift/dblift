import { request } from "./client";
import type { FlywayRead } from "./types";

export const readFlyway = (root: string, path: string) =>
  request<FlywayRead>("/flyway/read", { method: "POST", body: JSON.stringify({ root, path }) });
