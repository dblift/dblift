import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { CommandRun } from "../commands/useCommand";
import FlywayImport from "./FlywayImport";

const result = { success: true, error: null, current_version: null, migrations: [], sql: [], repaired: null, baseline_version: null, job_id: "j", has_log: true, message: null };
const finished = (command: string, message: string | null, error: string | null = null): CommandRun => ({
  command, phase: error ? "failed" : "done", events: [], error,
  result: { ...result, success: !error, error, message },
});

function banner(overrides: Partial<Parameters<typeof FlywayImport>[0]> = {}) {
  const props = { table: "flyway_schema_history", busy: false, run: null, onPreview: vi.fn(), onImport: vi.fn(), ...overrides };
  render(<FlywayImport {...props} />);
  return props;
}

it("explains and names the table", () => {
  banner({ table: "schema_version" });

  const region = screen.getByRole("region", { name: "Flyway history" });
  expect(region).toHaveTextContent(/comes from Flyway/);
  expect(region).toHaveTextContent("schema_version");
  expect(region).toHaveTextContent(/before migrating/);
});

it("previews", async () => {
  const props = banner();

  await userEvent.click(screen.getByRole("button", { name: "Preview the import" }));

  expect(props.onPreview).toHaveBeenCalledTimes(1);
  expect(props.onImport).not.toHaveBeenCalled();
});

it("shows what a preview found", () => {
  banner({ run: finished("flyway_preview", "2 entries would be imported from flyway_schema_history") });

  expect(screen.getByRole("status")).toHaveTextContent("2 entries would be imported");
});

it("shows why a preview failed", () => {
  banner({ run: finished("flyway_preview", null, "flyway_schema_history table not found in schema 'main'.") });

  expect(screen.getByRole("alert")).toHaveTextContent("table not found");
});

it("ignores the result of another command", () => {
  banner({ run: finished("validate", "all good") });

  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("asks before importing", async () => {
  const props = banner();

  await userEvent.click(screen.getByRole("button", { name: "Import history" }));
  expect(props.onImport).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Import history" }));
  await userEvent.click(screen.getByRole("button", { name: "Import" }));
  expect(props.onImport).toHaveBeenCalledTimes(1);
});

it("waits while a command runs", () => {
  banner({ busy: true });

  const region = screen.getByRole("region", { name: "Flyway history" });
  within(region).getAllByRole("button").forEach((button) => expect(button).toBeDisabled());
});
