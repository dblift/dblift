import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import App from "./App";

const api = vi.hoisted(() => ({
  listProjects: vi.fn(),
  addProject: vi.fn(),
  removeProject: vi.fn(),
  setEnvironment: vi.fn(),
}));
vi.mock("./api/projects", () => api);
const runJob = vi.hoisted(() => vi.fn());
vi.mock("./api/jobs", () => ({ runJob }));

beforeEach(() => {
  api.listProjects.mockReset();
  api.setEnvironment.mockReset();
  runJob.mockReset();
  runJob.mockResolvedValue({
    success: true, error: null, current_version: null, migrations: [], sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false,
  });
});

it("invites the user to add a project when there is none", async () => {
  api.listProjects.mockResolvedValue([]);
  render(<App />);

  expect(screen.getByRole("application", { name: "DBLift UI" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: /Add your first project/ })).toBeInTheDocument();
});

it("opens the first project", async () => {
  api.listProjects.mockResolvedValue([
    { id: "p1", name: "shop-api", config_path: "/w/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null },
  ]);
  render(<App />);

  expect(await screen.findByRole("heading", { name: "shop-api" })).toBeInTheDocument();
});

it("explains a rejected token instead of showing an empty screen", async () => {
  api.listProjects.mockRejectedValue(new Error("invalid token"));
  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid token/);
});

it("keeps the chosen environment when the user comes back to a project", async () => {
  const alpha = { id: "a1", name: "alpha", config_path: "/a/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null };
  const beta = { ...alpha, id: "b1", name: "beta" };
  api.listProjects.mockResolvedValue([alpha, beta]);
  api.setEnvironment.mockResolvedValue({ ...alpha, last_environment: "staging" });
  render(<App />);

  expect(await screen.findByRole("heading", { name: "alpha" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "staging" }));
  expect(api.setEnvironment).toHaveBeenCalledWith("a1", "staging");

  await userEvent.click(screen.getByRole("button", { name: /^beta/ }));
  expect(await screen.findByRole("heading", { name: "beta" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /^alpha/ }));
  expect(await screen.findByRole("heading", { name: "alpha" })).toBeInTheDocument();

  expect(screen.getByRole("tab", { name: "staging" })).toHaveAttribute("aria-selected", "true");
  await waitFor(() => expect(runJob).toHaveBeenLastCalledWith("a1", "info", "staging", expect.any(Function)));
});

it("says so when the chosen environment cannot be saved", async () => {
  const gamma = { id: "g1", name: "gamma", config_path: "/g/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null };
  api.listProjects.mockResolvedValue([gamma]);
  api.setEnvironment.mockRejectedValue(new Error("registry file is read-only"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: "gamma" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "staging" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("registry file is read-only");
  expect(screen.getByRole("tab", { name: "staging" })).toHaveAttribute("aria-selected", "true");
  expect(runJob).toHaveBeenLastCalledWith("g1", "info", "staging", expect.any(Function));
});
