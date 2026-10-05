import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { CommandRun } from "../commands/useCommand";
import RunLog from "./RunLog";

const api = vi.hoisted(() => ({ readJobLog: vi.fn() }));
vi.mock("../api/jobs", () => api);

function run(hasLog: boolean): CommandRun {
  return {
    command: "migrate", phase: "done", events: [{ event: "migration.completed" }], error: null,
    result: { success: true, error: null, current_version: "1.0.1", migrations: [], sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: hasLog },
  };
}

beforeEach(() => {
  api.readJobLog.mockReset();
});

it("loads and shows the full log on demand", async () => {
  api.readJobLog.mockResolvedValue("Statement executed successfully\nMigration V1_0_0__a.sql executed in 3ms\n");
  render(<RunLog run={run(true)} onDismiss={() => {}} />);
  expect(api.readJobLog).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("button", { name: "Full log" }));

  expect(api.readJobLog).toHaveBeenCalledWith("j1");
  expect(await screen.findByText(/Statement executed successfully/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Hide full log" }));
  expect(screen.queryByText(/Statement executed successfully/)).not.toBeInTheDocument();
});

it("offers no full log when the run has none", () => {
  render(<RunLog run={run(false)} onDismiss={() => {}} />);
  expect(screen.queryByRole("button", { name: "Full log" })).not.toBeInTheDocument();
});

it("says so when the full log cannot be loaded", async () => {
  api.readJobLog.mockRejectedValue(new Error("this job has no log"));
  render(<RunLog run={run(true)} onDismiss={() => {}} />);

  await userEvent.click(screen.getByRole("button", { name: "Full log" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("this job has no log");
});
