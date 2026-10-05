import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { JobEvent, JobResult, Migration, Project } from "../api/types";
import StatusView from "./StatusView";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob }));

const project: Project = {
  id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "",
  environments: ["staging"], engine: "sqlite", error: null,
};

function migration(script: string, status: string): Migration {
  const [version, name] = script.slice(1).replace(".sql", "").split("__");
  return {
    script, version: version.replaceAll("_", "."), description: name, type: "SQL", status,
    installed_on: status === "PENDING" ? "" : "2026-10-05 10:00:00", installed_by: "dev", execution_time: 3,
  };
}

function result(migrations: Migration[], extra: Partial<JobResult> = {}): JobResult {
  return { success: true, error: null, current_version: null, migrations, sql: [], repaired: null, baseline_version: null, ...extra };
}

const A = "V1_0_0__create_customers.sql";
const B = "V1_0_1__create_orders.sql";

type Handler = (onEvent: (e: JobEvent) => void) => Promise<JobResult>;

/** Route each command the view runs to a scripted answer. */
function script(handlers: Record<string, Handler | JobResult>) {
  runJob.mockImplementation((_p: string, command: string, _e: string, onEvent: (e: JobEvent) => void) => {
    const handler = handlers[command];
    if (!handler) {
      throw new Error(`unexpected command ${command}`);
    }
    return typeof handler === "function" ? handler(onEvent) : Promise.resolve(handler);
  });
}

const commandsRun = () => runJob.mock.calls.map((call) => call[1]);

beforeEach(() => {
  runJob.mockReset();
});

it("previews the SQL, then applies only after confirmation", async () => {
  let applied = false;
  script({
    info: () => Promise.resolve(result([migration(A, applied ? "SUCCESS" : "PENDING"), migration(B, applied ? "SUCCESS" : "PENDING")], { current_version: applied ? "1.0.1" : null })),
    preview: result([], { sql: [{ script: A, statements: ["CREATE TABLE customers (id INTEGER PRIMARY KEY);"] }, { script: B, statements: ["CREATE TABLE orders (id INTEGER PRIMARY KEY);"] }] }),
    migrate: async (onEvent) => {
      onEvent({ event: "migration.started" });
      onEvent({ event: "migration.script.completed", script: A, execution_time: 4 });
      onEvent({ event: "migration.script.completed", script: B, execution_time: 2 });
      applied = true;
      return result([], { current_version: "1.0.1" });
    },
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));

  const preview = await screen.findByRole("region", { name: "SQL to be applied" });
  expect(within(preview).getByText("CREATE TABLE customers (id INTEGER PRIMARY KEY);")).toBeInTheDocument();
  expect(commandsRun()).not.toContain("migrate");

  await userEvent.click(within(preview).getByRole("button", { name: "Apply 2 migrations" }));

  const log = await screen.findByRole("log");
  await waitFor(() => expect(within(log).getByText(`Applied ${B} in 2 ms`)).toBeInTheDocument());
  await waitFor(() => expect(screen.getByText("Version", { selector: "dt" }).nextElementSibling).toHaveTextContent("1.0.1"));
  expect(commandsRun().filter((c) => c === "info")).toHaveLength(2);
  expect(screen.queryByRole("region", { name: "SQL to be applied" })).not.toBeInTheDocument();
});

it("cancelling the preview applies nothing", async () => {
  script({
    info: result([migration(A, "PENDING")]),
    preview: result([], { sql: [{ script: A, statements: ["CREATE TABLE customers (id INTEGER PRIMARY KEY);"] }] }),
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));

  expect(screen.queryByRole("region", { name: "SQL to be applied" })).not.toBeInTheDocument();
  expect(commandsRun()).toEqual(["info", "preview"]);
});

it("shows a script as running, then applied, while the run is in flight", async () => {
  let release: () => void = () => {};
  script({
    info: result([migration(A, "PENDING"), migration(B, "PENDING")]),
    preview: result([], { sql: [{ script: A, statements: ["x"] }, { script: B, statements: ["y"] }] }),
    migrate: (onEvent) =>
      new Promise<JobResult>((resolve) => {
        onEvent({ event: "migration.script.completed", script: A });
        onEvent({ event: "migration.script.started", script: B });
        release = () => resolve(result([]));
      }),
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  const grid = await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  await userEvent.click(await screen.findByRole("button", { name: "Apply 2 migrations" }));

  await waitFor(() => expect(within(grid).getByText("Running")).toBeInTheDocument());
  expect(within(grid).getByText("Applied")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "staging" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();

  release();
  await waitFor(() => expect(screen.getByRole("tab", { name: "staging" })).toBeEnabled());
});

it("shows why a migration failed and offers repair afterwards", async () => {
  let failed = false;
  script({
    info: () => Promise.resolve(result([migration(A, failed ? "FAILED" : "PENDING")])),
    preview: result([], { sql: [{ script: A, statements: ["SELEC nonsense;"] }] }),
    migrate: async (onEvent) => {
      onEvent({ event: "migration.script.failed", script: A, error: 'near "SELEC": syntax error' });
      failed = true;
      return result([], { success: false, error: `Failed to execute statement 1 in ${A}: near "SELEC": syntax error` });
    },
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  await userEvent.click(await screen.findByRole("button", { name: "Apply 1 migration" }));

  const log = await screen.findByRole("log");
  await waitFor(() => expect(within(log).getByText(/Failed to execute statement 1/)).toBeInTheDocument());
  expect(await screen.findByRole("button", { name: "Repair" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Migrate" })).toBeDisabled();
});

it("explains a refused command", async () => {
  script({
    info: result([migration(A, "SUCCESS")], { current_version: "1.0.0" }),
    undo: () => Promise.reject(new Error("Another change is running on this project. Wait for it to finish.")),
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: "Undo last migration" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  expect(await within(await screen.findByRole("log")).findByText(/Another change is running/)).toBeInTheDocument();
});

it("lets the user close the run log", async () => {
  script({ info: result([migration(A, "SUCCESS")], { current_version: "1.0.0" }), validate: result([]) });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: "Validate" }));
  await screen.findByRole("log");
  await userEvent.click(screen.getByRole("button", { name: "Close log" }));

  expect(screen.queryByRole("log")).not.toBeInTheDocument();
});
