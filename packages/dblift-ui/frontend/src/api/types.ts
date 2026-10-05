export interface Project {
  id: string;
  name: string;
  config_path: string;
  last_environment: string;
  environments: string[];
  engine: string;
  error: string | null;
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

export interface JobResult {
  success: boolean;
  error: string | null;
  current_version: string | null;
  migrations: Migration[];
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
