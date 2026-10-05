import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
const scripts = vi.hoisted(() => ({ listScripts: vi.fn(), readScript: vi.fn() }));
vi.mock("./api/scripts", () => scripts);
const discovery = vi.hoisted(() => ({
  getDefaults: vi.fn(async () => ({ clone_parent: "/home/dev/dblift-projects", git: true })),
  discoverFolder: vi.fn(async () => ({
    root: "/work/platform", name: "platform", repository: true, branch: "main", truncated: false, flyway: [], script_folders: [],
    configs: [{ path: "dblift.yaml", kind: "named", problem: null, registered: false }],
  })),
  cloneRepository: vi.fn(),
}));
vi.mock("./api/discovery", () => discovery);
vi.mock("./components/CodeEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

const first = {
  id: "p1", name: "shop-api", config_path: "/w/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null,
  missing: false, repository: "w", repository_path: "/w",
};

beforeEach(() => {
  api.listProjects.mockReset();
  api.setEnvironment.mockReset();
  api.removeProject.mockReset();
  scripts.listScripts.mockReset();
  scripts.listScripts.mockResolvedValue([]);
  scripts.readScript.mockReset();
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
  api.listProjects.mockResolvedValue([first]);
  render(<App />);

  expect(await screen.findByRole("heading", { name: "shop-api" })).toBeInTheDocument();
});

it("adds a project through the dialog and opens it", async () => {
  api.listProjects.mockResolvedValueOnce([]).mockResolvedValue([{ ...first, id: "new", name: "platform" }]);
  api.addProject.mockResolvedValue({ ...first, id: "new", name: "platform" });
  render(<App />);
  await screen.findByRole("heading", { name: /Add your first project/ });

  await userEvent.click(screen.getByRole("button", { name: "Add project" }));
  await userEvent.type(screen.getByLabelText("Folder path"), "/work/platform");
  await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
  await userEvent.click(await screen.findByRole("button", { name: "Add 1 project" }));

  expect(await screen.findByRole("heading", { name: "platform" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("explains a rejected token instead of showing an empty screen", async () => {
  api.listProjects.mockRejectedValue(new Error("invalid token"));
  render(<App />);

  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid token/);
});

it("keeps the chosen environment when the user comes back to a project", async () => {
  const alpha = { id: "a1", name: "alpha", config_path: "/a/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null, missing: false, repository: "a", repository_path: "/a" };
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
  const gamma = { id: "g1", name: "gamma", config_path: "/g/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null, missing: false, repository: "g", repository_path: "/g" };
  api.listProjects.mockResolvedValue([gamma]);
  api.setEnvironment.mockRejectedValue(new Error("registry file is read-only"));
  render(<App />);

  expect(await screen.findByRole("heading", { name: "gamma" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: "staging" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("registry file is read-only");
  expect(screen.getByRole("tab", { name: "staging" })).toHaveAttribute("aria-selected", "true");
  expect(runJob).toHaveBeenLastCalledWith("g1", "info", "staging", expect.any(Function));
});

describe("unsaved edits in the open script", () => {
  const delta = { id: "d1", name: "delta", config_path: "/d/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null, missing: false, repository: "d", repository_path: "/d" };
  const epsilon = { ...delta, id: "e1", name: "epsilon", config_path: "/e/dblift.yaml", repository: "e", repository_path: "/e" };
  const A = "V1_0_0__create_accounts.sql";

  beforeEach(() => {
    api.listProjects.mockResolvedValue([delta, epsilon]);
    runJob.mockResolvedValue({
      success: true, error: null, current_version: null, sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false,
      migrations: [{ script: A, version: "1.0.0", description: "create_accounts", type: "SQL", status: "PENDING", installed_on: "", installed_by: "", execution_time: 0 }],
    });
    const listed = { name: A, kind: "versioned", version: "1.0.0", description: "create_accounts", language: "sql", directory: "migrations", has_undo: false };
    scripts.listScripts.mockResolvedValue([listed]);
    scripts.readScript.mockResolvedValue({ ...listed, content: "-- accounts\n" });
  });

  async function editInDelta() {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "delta" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: `Open ${A}` }));
    await userEvent.type(await screen.findByLabelText(`Content of ${A}`), "x");
  }

  it("asks before switching project, keeps editing or discards and switches", async () => {
    await editInDelta();

    await userEvent.click(screen.getByRole("button", { name: /^epsilon/ }));
    expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("heading", { name: "delta" })).toBeInTheDocument();
    expect(screen.getByLabelText(`Content of ${A}`)).toHaveValue("-- accounts\nx");

    await userEvent.click(screen.getByRole("button", { name: /^epsilon/ }));
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(await screen.findByRole("heading", { name: "epsilon" })).toBeInTheDocument();
    expect(screen.queryByLabelText(`Content of ${A}`)).not.toBeInTheDocument();
  });

  it("asks before opening the add-project dialog", async () => {
    await editInDelta();

    await userEvent.click(screen.getByRole("button", { name: "Add project" }));
    expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByRole("dialog", { name: "Add project" })).toBeInTheDocument();
  });

  it("asks before removing the open project", async () => {
    api.removeProject.mockResolvedValue(undefined);
    await editInDelta();

    await userEvent.click(screen.getByRole("button", { name: "Remove delta" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
    expect(api.removeProject).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(api.removeProject).toHaveBeenCalledWith("d1"));
  });
});
