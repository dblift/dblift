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
  flyway_table: string | null;
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
  message: string | null;
  /** What the scratch test found; null for every other job, and when the test itself could not run. */
  scratch: ScratchResult | null;
}

/** How the scratch test would run for a project, read before anything runs. */
export interface ScratchPlan {
  strategy: "file" | "environment" | "container" | "skip";
  engine: string;
  summary: string;
  warning: string;
  /** The container strategy only (empty or null otherwise): the runtime, the image, whether it is on this machine, its approximate size. */
  runtime: string;
  image: string;
  image_present: boolean | null;
  image_size_mb: number | null;
}

export interface ScratchPhase {
  name: "start" | "clean" | "build" | "undo" | "reapply";
  /** null: the phase was skipped. */
  ok: boolean | null;
  detail: string;
}

export interface ScratchResult {
  strategy: string;
  passed: boolean;
  skipped: boolean;
  phases: ScratchPhase[];
  script: string;
  /** Present only when the scratch container could not be removed, or its removal checked. */
  cleanup?: string;
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
  /** A "scratch.phase" event: which phase, and whether it started, passed, failed or was skipped. */
  phase?: ScratchPhase["name"];
  status?: "started" | "passed" | "failed" | "skipped";
  detail?: string;
}

export interface Script {
  name: string;
  kind: "versioned" | "undo" | "repeatable";
  version: string;
  description: string;
  language: "sql" | "python";
  directory: string;
  has_undo: boolean;
  /** The file's path relative to the repository's root, or "" outside a repository. */
  path: string;
  /** The file's git state ("modified", "untracked"…), or "" when it is committed as is. */
  change: string;
  /** The undo script's path relative to the repository's root, or "" when there is none. */
  undo_path: string;
  /** The undo script's git state, or "" when it is committed as is or there is none. */
  undo_change: string;
}

export interface ChangedFile {
  path: string;
  state: "untracked" | "modified" | "added" | "deleted" | "renamed" | "conflicted";
}

export interface RepoStatus {
  repository: boolean;
  root?: string;
  branch?: string;
  detached?: boolean;
  upstream?: string;
  ahead?: number;
  behind?: number;
  files?: ChangedFile[];
  truncated?: boolean;
}

/** A "new pull request" page for the current branch; url is null when the host is unknown. */
export interface PullRequestLink {
  url: string | null;
  kind: string | null;
  branch: string;
}

export interface Branch {
  name: string;
  current: boolean;
  remote: boolean;
  upstream: string;
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

export interface FlywayRead {
  folder: string;
  form: ConfigFormData;
  table: string;
  notes: string[];
}

export interface ConfigDocument {
  form: ConfigFormData;
  revision: string;
  notes: string[];
}
