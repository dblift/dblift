import { request } from "./client";
import type { ScratchPlan } from "./types";

/** How the scratch test would run for this project; nothing runs. */
export const getScratchPlan = (projectId: string) => request<ScratchPlan>(`/projects/${projectId}/scratch`);
