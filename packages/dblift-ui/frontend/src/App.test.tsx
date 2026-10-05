import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { Discovery, EngineSpec } from "./api/types";
import { emptyForm } from "./config/defaults";

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
  discoverFolder: vi.fn(async (): Promise<Discovery> => ({
    root: "/work/platform", name: "platform", repository: true, branch: "main", truncated: false, flyway: [], script_folders: [],
    configs: [{ path: "dblift.yaml", kind: "named", problem: null, registered: false }],
  })),
  cloneRepository: vi.fn(),
}));
vi.mock("./api/discovery", () => discovery);
const configs = vi.hoisted(() => ({
  getEngines: vi.fn(), previewConfig: vi.fn(), createConfig: vi.fn(), readConfig: vi.fn(), updateConfig: vi.fn(),
}));
vi.mock("./api/configs", () => configs);
const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(),
}));
vi.mock("./api/git", () => git);
vi.mock("./components/CodeEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

const sqlite: EngineSpec = { id: "sqlite", label: "SQLite", scheme: "sqlite", port: null, fields: ["path"] };
const first = {
  id: "p1", name: "shop-api", config_path: "/w/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null,
  missing: false, repository: "w", repository_path: "/w", flyway_table: null,
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
    success: true, error: null, current_version: null, migrations: [], sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null,
  });
  Object.values(git).forEach((mock) => mock.mockReset());
  git.getRepo.mockResolvedValue({ repository: false });
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
  const alpha = { id: "a1", name: "alpha", config_path: "/a/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null, missing: false, repository: "a", repository_path: "/a", flyway_table: null };
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
  const gamma = { id: "g1", name: "gamma", config_path: "/g/dblift.yaml", last_environment: "", environments: ["staging"], engine: "sqlite", error: null, missing: false, repository: "g", repository_path: "/g", flyway_table: null };
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
  const delta = { id: "d1", name: "delta", config_path: "/d/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null, missing: false, repository: "d", repository_path: "/d", flyway_table: null };
  const epsilon = { ...delta, id: "e1", name: "epsilon", config_path: "/e/dblift.yaml", repository: "e", repository_path: "/e" };
  const A = "V1_0_0__create_accounts.sql";

  beforeEach(() => {
    api.listProjects.mockResolvedValue([delta, epsilon]);
    runJob.mockResolvedValue({
      success: true, error: null, current_version: null, sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null,
      migrations: [{ script: A, version: "1.0.0", description: "create_accounts", type: "SQL", status: "PENDING", installed_on: "", installed_by: "", execution_time: 0 }],
    });
    const listed = { name: A, kind: "versioned", version: "1.0.0", description: "create_accounts", language: "sql", directory: "migrations", has_undo: false, path: "", change: "", undo_path: "", undo_change: "" };
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

  it("asks before opening the configuration", async () => {
    configs.getEngines.mockReset();
    configs.getEngines.mockResolvedValue([sqlite]);
    configs.readConfig.mockReset();
    configs.readConfig.mockReturnValue(new Promise(() => {}));
    await editInDelta();

    await userEvent.click(screen.getByRole("button", { name: "Configuration" }));
    expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(await screen.findByRole("dialog", { name: "Configuration of delta" })).toBeInTheDocument();
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

describe("the configuration form", () => {
  const form = { ...emptyForm(sqlite, "./migrations"), connection: { ...emptyForm(sqlite, "").connection, path: "./dev.db" } };

  beforeEach(() => {
    Object.values(configs).forEach((mock) => mock.mockReset());
    configs.getEngines.mockResolvedValue([sqlite]);
    configs.readConfig.mockResolvedValue({ form, revision: "r1", notes: [] });
    configs.previewConfig.mockResolvedValue({ yaml: "database:\n  type: sqlite\n", problems: [], warnings: [] });
  });

  it("edits the open project's configuration, then shows its new environments and reads its status again", async () => {
    const staged = { ...first, environments: ["staging"] };
    api.listProjects.mockResolvedValueOnce([first]).mockResolvedValue([staged]);
    configs.updateConfig.mockResolvedValue(staged);
    render(<App />);
    await screen.findByRole("heading", { name: "shop-api" });
    await screen.findByText("No migrations found in this project.");
    runJob.mockClear();

    await userEvent.click(screen.getByRole("button", { name: "Configuration" }));
    const dialog = await screen.findByRole("dialog", { name: "Configuration of shop-api" });
    expect(await within(dialog).findByLabelText("Database file")).toHaveValue("./dev.db");
    const save = within(dialog).getByRole("button", { name: "Save" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);

    expect(await screen.findByRole("tab", { name: "staging" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(configs.updateConfig).toHaveBeenCalledWith("p1", form, "r1");
    await waitFor(() => expect(runJob).toHaveBeenCalledWith("p1", "info", "", expect.any(Function)));
  });

  it("creates a configuration from the add-project dialog and opens the new project", async () => {
    const bare = { ...first, id: "b1", name: "bare", config_path: "/work/bare/dblift.yaml", repository: "bare", repository_path: "/work/bare" };
    api.listProjects.mockResolvedValueOnce([first]).mockResolvedValue([first, bare]);
    discovery.discoverFolder.mockResolvedValueOnce({
      root: "/work/bare", name: "bare", repository: false, branch: "", truncated: false, flyway: [], script_folders: ["sql"], configs: [],
    });
    configs.createConfig.mockResolvedValue(bare);
    render(<App />);
    await screen.findByRole("heading", { name: "shop-api" });

    await userEvent.click(screen.getByRole("button", { name: "Add project" }));
    await userEvent.type(screen.getByLabelText("Folder path"), "/work/bare");
    await userEvent.click(screen.getByRole("button", { name: "Look for configs" }));
    await userEvent.click(await screen.findByRole("button", { name: "Create configuration" }));

    const dialog = await screen.findByRole("dialog", { name: "New configuration" });
    expect(screen.queryByRole("dialog", { name: "Add project" })).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Migrations folder")).toHaveValue("./sql");
    const create = within(dialog).getByRole("button", { name: "Create" });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);

    expect(await screen.findByRole("heading", { name: "bare" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(configs.createConfig).toHaveBeenCalledWith("/work/bare", "dblift.yaml", "bare", expect.objectContaining({ migrations_directory: "./sql" }));
  });

  it("explains a configuration that cannot be read, and offers only to close", async () => {
    api.listProjects.mockResolvedValue([{ ...first, error: "config file not found" }]);
    configs.readConfig.mockRejectedValue(new Error("config file not found: /w/dblift.yaml"));
    render(<App />);
    await screen.findByRole("heading", { name: "shop-api" });

    await userEvent.click(screen.getByRole("button", { name: "Configuration" }));

    const dialog = await screen.findByRole("dialog", { name: "Configuration of shop-api" });
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("config file not found: /w/dblift.yaml");
    expect(within(dialog).getAllByRole("button").map((b) => b.textContent)).toEqual(["Close"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("following the branch", () => {
  const platform = {
    ...first, id: "pl", name: "platform", config_path: "/work/platform/dblift.yaml", repository: "platform", repository_path: "/work/platform",
  };
  const main = {
    repository: true, root: "/work/platform", branch: "main", detached: false, upstream: "origin/main", ahead: 0, behind: 0, files: [], truncated: false,
  };

  beforeEach(() => {
    api.listProjects.mockResolvedValue([platform]);
    let checkedOut: object = main;
    git.getRepo.mockImplementation(async () => checkedOut);
    git.getBranches.mockResolvedValue([
      { name: "main", current: true, remote: false, upstream: "origin/main" },
      { name: "origin/feature/reporting", current: false, remote: true, upstream: "" },
    ]);
    git.switchBranch.mockImplementation(async () => (checkedOut = { ...main, branch: "feature/reporting", upstream: "origin/feature/reporting" }));
    discovery.discoverFolder.mockReset();
    discovery.discoverFolder.mockResolvedValue({
      root: "/work/platform", name: "platform", repository: true, branch: "feature/reporting", truncated: false, flyway: [], script_folders: [],
      configs: [
        { path: "dblift.yaml", kind: "named", problem: null, registered: true },
        { path: "reporting/dblift.yaml", kind: "named", problem: null, registered: false },
        { path: "dblift.yaml.template", kind: "template", problem: null, registered: false },
        { path: "broken/dblift.yaml", kind: "named", problem: "line 1: not a mapping", registered: false },
      ],
    });
  });

  it("offers to add the configs a switch brought in, and opens Add project on them", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "platform" });
    await userEvent.click(await screen.findByRole("button", { name: "Branch main" }));
    await userEvent.click(await screen.findByRole("button", { name: "origin/feature/reporting" }));

    expect(await screen.findByRole("button", { name: "Branch feature/reporting" })).toBeInTheDocument();
    const notice = await screen.findByText("1 configuration on this branch is not a project yet.");
    expect(discovery.discoverFolder).toHaveBeenCalledWith("/work/platform");
    await waitFor(() => expect(api.listProjects).toHaveBeenCalledTimes(2));

    await userEvent.click(within(notice.closest("[role=status]") as HTMLElement).getByRole("button", { name: "Add" }));

    const dialog = await screen.findByRole("dialog", { name: "Add project" });
    expect(await within(dialog).findByRole("checkbox", { name: "reporting/dblift.yaml" })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "dblift.yaml" })).toBeDisabled();
    expect(screen.queryByText("1 configuration on this branch is not a project yet.")).not.toBeInTheDocument();
  });

  it("says nothing when the branch brings no new config", async () => {
    discovery.discoverFolder.mockResolvedValue({
      root: "/work/platform", name: "platform", repository: true, branch: "feature/reporting", truncated: false, flyway: [], script_folders: [],
      configs: [{ path: "dblift.yaml", kind: "named", problem: null, registered: true }],
    });
    render(<App />);
    await screen.findByRole("heading", { name: "platform" });
    await userEvent.click(await screen.findByRole("button", { name: "Branch main" }));
    await userEvent.click(await screen.findByRole("button", { name: "origin/feature/reporting" }));

    await waitFor(() => expect(discovery.discoverFolder).toHaveBeenCalledWith("/work/platform"));
    expect(screen.queryByText(/on this branch/)).not.toBeInTheDocument();
  });
});
