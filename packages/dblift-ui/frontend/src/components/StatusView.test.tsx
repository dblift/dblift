import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { JobResult, Project } from "../api/types";
import StatusView from "./StatusView";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob }));
vi.mock("../api/scripts", () => ({ listScripts: vi.fn().mockResolvedValue([]) }));
vi.mock("./CodeEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

function view(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}

const project: Project = {
  id: "p1",
  name: "shop-api",
  config_path: "/work/shop/dblift.yaml",
  last_environment: "",
  environments: ["staging"],
  engine: "postgresql",
  error: null,
  missing: false,
  repository: "shop",
  repository_path: "/work/shop",
  flyway_table: null,
};

const status: JobResult = {
  success: true,
  error: null,
  current_version: "1.0.1",
  migrations: [
    { script: "V1_0_0__create_customers.sql", version: "1.0.0", description: "create_customers", type: "SQL", status: "SUCCESS", installed_on: "2026-10-04 21:24:55", installed_by: "dev", execution_time: 7 },
    { script: "V1_0_1__create_orders.sql", version: "1.0.1", description: "create_orders", type: "SQL", status: "SUCCESS", installed_on: "2026-10-04 21:24:55", installed_by: "dev", execution_time: 3 },
    { script: "V1_0_2__add_phone.sql", version: "1.0.2", description: "add_phone", type: "SQL", status: "PENDING", installed_on: "", installed_by: "", execution_time: 0 },
  ],
  sql: [],
  repaired: null,
  baseline_version: null,
  job_id: "j1",
  has_log: false, message: null, scratch: null,
};

beforeEach(() => {
  runJob.mockReset();
  runJob.mockResolvedValue(status);
});

it("shows the project, its counts, the rail and the grid", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  expect(screen.getByRole("heading", { name: "shop-api" })).toBeInTheDocument();
  const grid = await screen.findByRole("table", { name: "Migrations" });
  expect(within(grid).getAllByRole("row")).toHaveLength(4);
  expect(within(grid).getByText("create customers")).toBeInTheDocument();
  expect(within(grid).getAllByText("Applied")).toHaveLength(2);
  expect(within(grid).getByText("Pending")).toBeInTheDocument();
  expect(screen.getByText("Applied", { selector: "dt" }).nextElementSibling).toHaveTextContent("2");
  expect(screen.getByText("Pending", { selector: "dt" }).nextElementSibling).toHaveTextContent("1");
  expect(screen.getByText("Version", { selector: "dt" }).nextElementSibling).toHaveTextContent("1.0.1");
  expect(screen.getByRole("list", { name: "Migration timeline" }).children).toHaveLength(3);
});

it("offers the environments and reports the one chosen", async () => {
  const onEnvironmentChange = vi.fn();
  render(view(<StatusView project={project} onEnvironmentChange={onEnvironmentChange} />));
  await screen.findByRole("table", { name: "Migrations" });

  expect(screen.getByRole("tab", { name: "default" })).toHaveAttribute("aria-selected", "true");
  await userEvent.click(screen.getByRole("tab", { name: "staging" }));

  expect(onEnvironmentChange).toHaveBeenCalledWith("staging");
});

it("opens the configuration from the header", async () => {
  const onConfigure = vi.fn();
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} onConfigure={onConfigure} />));

  await userEvent.click(await screen.findByRole("button", { name: "Configuration" }));

  expect(onConfigure).toHaveBeenCalledTimes(1);
});

it("runs the status for the remembered environment", async () => {
  render(view(<StatusView project={{ ...project, last_environment: "staging" }} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  expect(runJob).toHaveBeenCalledWith("p1", "info", "staging", expect.any(Function));
  expect(screen.getByRole("tab", { name: "staging" })).toHaveAttribute("aria-selected", "true");
});

it("shows the error and lets the user retry", async () => {
  runJob.mockResolvedValueOnce({
    success: false, error: "cannot connect to db.local", current_version: null, migrations: [], sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null, scratch: null,
  });
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  expect(await screen.findByRole("alert")).toHaveTextContent("cannot connect to db.local");
  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("table", { name: "Migrations" })).toBeInTheDocument();
});

it("says so when a project has no migration yet", async () => {
  runJob.mockResolvedValue({ ...status, current_version: null, migrations: [] });
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  expect(await screen.findByText("No migrations found in this project.")).toBeInTheDocument();
});

it("describes the running job in words", async () => {
  runJob.mockImplementation((_p: string, _c: string, _e: string, onEvent: (event: { event: string }) => void) => {
    onEvent({ event: "info.started" });
    return new Promise(() => {});
  });
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  expect(await screen.findByText("Reading migration status…")).toBeInTheDocument();
  expect(screen.queryByText("info.started")).not.toBeInTheDocument();
});

it("shows a config problem reported by the server", () => {
  render(view(<StatusView project={{ ...project, error: "config is not a mapping" }} onEnvironmentChange={() => {}} />));

  expect(screen.getByRole("alert")).toHaveTextContent("config is not a mapping");
});

const pending = { ...status, current_version: null, migrations: status.migrations.map((m) => ({ ...m, status: "PENDING", installed_on: "" })) };
const fromFlyway = { ...project, flyway_table: "flyway_schema_history" };

it("offers to import the Flyway history while nothing is applied", async () => {
  runJob.mockImplementation((_p: string, command: string) =>
    Promise.resolve(command === "flyway_preview" ? { ...status, message: "2 entries would be imported from flyway_schema_history" } : pending),
  );
  render(view(<StatusView project={fromFlyway} onEnvironmentChange={() => {}} />));

  const banner = await screen.findByRole("region", { name: "Flyway history" });
  // Above the command bar: the import comes before migrating.
  expect(banner.compareDocumentPosition(screen.getByRole("button", { name: "Migrate" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await userEvent.click(within(banner).getByRole("button", { name: "Preview the import" }));

  expect(runJob).toHaveBeenCalledWith("p1", "flyway_preview", "", expect.any(Function), { table: "flyway_schema_history" });
  expect(await within(banner).findByRole("status")).toHaveTextContent("2 entries would be imported");
});

it("offers no Flyway import once a migration is applied", async () => {
  render(view(<StatusView project={fromFlyway} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  expect(screen.queryByRole("region", { name: "Flyway history" })).not.toBeInTheDocument();
});

it("offers no Flyway import for a project that does not come from Flyway", async () => {
  runJob.mockResolvedValue(pending);
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  expect(screen.queryByRole("region", { name: "Flyway history" })).not.toBeInTheDocument();
});
