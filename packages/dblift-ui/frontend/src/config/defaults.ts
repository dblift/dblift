import type { ConfigFormData, ConnectionForm, EngineSpec } from "../api/types";

export const ENV_DEFAULT = "DBLIFT_DB_PASSWORD";

/** A connection with nothing typed. An inherited one (an environment's) has no port and no password of its own. */
export function emptyConnection(engine?: EngineSpec, inherit = false): ConnectionForm {
  const password = !inherit && engine?.fields.includes("password");
  return {
    mode: "fields",
    url: "",
    host: "",
    port: inherit ? null : (engine?.port ?? null),
    database: "",
    service_name: "",
    account: "",
    warehouse: "",
    path: "",
    username: "",
    schema: "",
    password: password ? { mode: "env", value: ENV_DEFAULT } : { mode: "none", value: "" },
  };
}

export function emptyForm(engine: EngineSpec, migrations: string): ConfigFormData {
  return {
    engine: engine.id,
    connection: emptyConnection(engine),
    migrations_directory: migrations,
    recursive: true,
    log_level: "INFO",
    strict_mode: false,
    clean_disabled: true,
    environments: [],
  };
}

/** The same form for another engine: connection fields restart, what still applies is kept. */
export function withEngine(form: ConfigFormData, engine: EngineSpec): ConfigFormData {
  const connection = emptyConnection(engine);
  if (engine.fields.includes("username")) {
    connection.username = form.connection.username;
  }
  if (engine.fields.includes("schema")) {
    connection.schema = form.connection.schema;
  }
  return {
    ...form,
    engine: engine.id,
    connection,
    environments: form.environments.map((e) => ({ name: e.name, connection: emptyConnection(engine, true) })),
  };
}
