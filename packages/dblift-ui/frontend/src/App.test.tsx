import { render, screen } from "@testing-library/react";
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
  runJob.mockReset();
  runJob.mockResolvedValue({ success: true, error: null, current_version: null, migrations: [] });
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
