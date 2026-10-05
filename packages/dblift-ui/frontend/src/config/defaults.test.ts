import { expect, it } from "vitest";

import type { EngineSpec } from "../api/types";
import { emptyConnection, emptyForm, withEngine } from "./defaults";

const pg: EngineSpec = { id: "postgresql", label: "PostgreSQL", scheme: "postgresql", port: 5432, fields: ["host", "port", "database", "username", "password", "schema"] };
const mysql: EngineSpec = { id: "mysql", label: "MySQL", scheme: "mysql", port: 3306, fields: ["host", "port", "database", "username", "password"] };
const sqlite: EngineSpec = { id: "sqlite", label: "SQLite", scheme: "sqlite", port: null, fields: ["path"] };

it("starts a form with the engine's port and a placeholder password", () => {
  const form = emptyForm(pg, "./db/migrations");

  expect(form.engine).toBe("postgresql");
  expect(form.connection.port).toBe(5432);
  expect(form.connection.password).toEqual({ mode: "env", value: "DBLIFT_DB_PASSWORD" });
  expect(form.migrations_directory).toBe("./db/migrations");
  expect([form.recursive, form.log_level, form.strict_mode, form.clean_disabled]).toEqual([true, "INFO", false, true]);
});

it("has no password for an engine without one", () => {
  expect(emptyForm(sqlite, "./migrations").connection.password.mode).toBe("none");
});

it("an inherited connection is empty", () => {
  const connection = emptyConnection(pg, true);

  expect(connection.port).toBeNull();
  expect(connection.password.mode).toBe("none");
});

it("changing engine keeps what still applies", () => {
  const form = emptyForm(pg, "./migrations");
  form.connection.host = "db";
  form.connection.username = "app";
  form.connection.schema = "public";
  form.strict_mode = true;
  form.environments = [{ name: "staging", connection: { ...emptyConnection(pg, true), host: "stg" } }];

  const next = withEngine(form, mysql);

  expect(next.engine).toBe("mysql");
  expect(next.connection.port).toBe(3306);
  expect(next.connection.host).toBe("");
  expect(next.connection.username).toBe("app");
  expect(next.connection.schema).toBe("");
  expect(next.strict_mode).toBe(true);
  expect(next.environments).toEqual([{ name: "staging", connection: emptyConnection(mysql, true) }]);
});
