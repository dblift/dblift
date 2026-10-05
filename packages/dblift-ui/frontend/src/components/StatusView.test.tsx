import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { JobResult, Project } from "../api/types";
import StatusView from "./StatusView";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob }));

const project: Project = {
  id: "p1",
  name: "shop-api",
  config_path: "/work/shop/dblift.yaml",
  last_environment: "",
  environments: ["staging"],
  engine: "postgresql",
  error: null,
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
};

beforeEach(() => {
  runJob.mockReset();
  runJob.mockResolvedValue(status);
});

it("shows the project, its counts, the rail and the grid", async () => {
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);

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
  render(<StatusView project={project} onEnvironmentChange={onEnvironmentChange} />);
  await screen.findByRole("table", { name: "Migrations" });

  expect(screen.getByRole("tab", { name: "default" })).toHaveAttribute("aria-selected", "true");
  await userEvent.click(screen.getByRole("tab", { name: "staging" }));

  expect(onEnvironmentChange).toHaveBeenCalledWith("staging");
});

it("runs the status for the remembered environment", async () => {
  render(<StatusView project={{ ...project, last_environment: "staging" }} onEnvironmentChange={() => {}} />);
  await screen.findByRole("table", { name: "Migrations" });

  expect(runJob).toHaveBeenCalledWith("p1", "info", "staging", expect.any(Function));
  expect(screen.getByRole("tab", { name: "staging" })).toHaveAttribute("aria-selected", "true");
});

it("shows the error and lets the user retry", async () => {
  runJob.mockResolvedValueOnce({ success: false, error: "cannot connect to db.local", current_version: null, migrations: [] });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("cannot connect to db.local");
  await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

  expect(await screen.findByRole("table", { name: "Migrations" })).toBeInTheDocument();
});

it("says so when a project has no migration yet", async () => {
  runJob.mockResolvedValue({ ...status, current_version: null, migrations: [] });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);

  expect(await screen.findByText("No migrations found in this project.")).toBeInTheDocument();
});

it("describes the running job in words", async () => {
  runJob.mockImplementation((_p: string, _c: string, _e: string, onEvent: (event: { event: string }) => void) => {
    onEvent({ event: "info.started" });
    return new Promise(() => {});
  });
  render(<StatusView project={project} onEnvironmentChange={() => {}} />);

  expect(await screen.findByText("Reading migration status…")).toBeInTheDocument();
  expect(screen.queryByText("info.started")).not.toBeInTheDocument();
});

it("shows a config problem reported by the server", () => {
  render(<StatusView project={{ ...project, error: "config is not a mapping" }} onEnvironmentChange={() => {}} />);

  expect(screen.getByRole("alert")).toHaveTextContent("config is not a mapping");
});
