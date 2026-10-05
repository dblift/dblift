export interface Project {
  id: string;
  name: string;
  config_path: string;
  last_environment: string;
  environments: string[];
  engine: string;
  error: string | null;
  repository: string;
  repository_path: string;
  missing: boolean;
}

export interface FoundConfig {
  path: string;
  kind: "named" | "content" | "template";
  problem: string | null;
  registered: boolean;
}

export interface Discovery {
  root: string;
  name: string;
  repository: boolean;
  branch: string;
  configs: FoundConfig[];
  flyway: string[];
  script_folders: string[];
  truncated: boolean;
}

export interface Defaults {
  clone_parent: string;
  git: boolean;
}

export interface Migration {
  script: string;
  version: string;
  description: string;
  type: string;
  status: string;
  installed_on: string;
  installed_by: string;
  execution_time: number;
}

export interface SqlPreview {
  script: string;
  statements: string[];
}

export interface JobResult {
  success: boolean;
  error: string | null;
  current_version: string | null;
  migrations: Migration[];
  sql: SqlPreview[];
  repaired: number | null;
  baseline_version: string | null;
  job_id: string;
  has_log: boolean;
}

export interface JobEvent {
  event: string;
  timestamp?: number;
  script?: string;
  version?: string;
  description?: string;
  execution_time?: number;
  error?: string;
  result?: JobResult;
}

export interface Script {
  name: string;
  kind: "versioned" | "undo" | "repeatable";
  version: string;
  description: string;
  language: "sql" | "python";
  directory: string;
  has_undo: boolean;
}

export interface ScriptFile extends Script {
  content: string;
}
