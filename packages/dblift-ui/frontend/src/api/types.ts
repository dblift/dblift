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

export interface EngineSpec {
  id: string;
  label: string;
  scheme: string;
  port: number | null;
  fields: string[];
}

export interface PasswordForm {
  mode: "env" | "literal" | "keep" | "none";
  value: string;
}

export interface ConnectionForm {
  mode: "fields" | "url";
  url: string;
  host: string;
  port: number | null;
  database: string;
  service_name: string;
  account: string;
  warehouse: string;
  path: string;
  username: string;
  schema: string;
  password: PasswordForm;
}

export interface EnvironmentForm {
  name: string;
  connection: ConnectionForm;
}

export interface ConfigFormData {
  engine: string;
  connection: ConnectionForm;
  migrations_directory: string;
  recursive: boolean;
  log_level: string;
  strict_mode: boolean;
  clean_disabled: boolean;
  environments: EnvironmentForm[];
}

export interface ConfigPreview {
  yaml: string;
  problems: string[];
  warnings: string[];
}

export interface ConfigDocument {
  form: ConfigFormData;
  revision: string;
  notes: string[];
}
