import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Branch, JobResult, Migration, Project, RepoStatus, Script } from "../api/types";
import StatusView from "./StatusView";

vi.mock("./CodeEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));
const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob, readJobLog: vi.fn() }));
const scripts = vi.hoisted(() => ({ listScripts: vi.fn(), readScript: vi.fn(), saveScript: vi.fn(), createScripts: vi.fn() }));
vi.mock("../api/scripts", () => scripts);
const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(),
}));
vi.mock("../api/git", () => git);

const project: Project = {
  id: "p1", name: "shop-api", config_path: "/work/shop/dblift.yaml", last_environment: "", environments: [], engine: "sqlite",
  error: null, missing: false, repository: "shop", repository_path: "/work/shop", flyway_table: null,
};
const A = "V1_0_0__create_customers.sql";
const B = "V1_0_1__create_orders.sql";
const main: RepoStatus = {
  repository: true, root: "/work/shop", branch: "main", detached: false, upstream: "origin/main", ahead: 0, behind: 0, files: [], truncated: false,
};
const branches: Branch[] = [
  { name: "main", current: true, remote: false, upstream: "origin/main" },
  { name: "feature/x", current: false, remote: false, upstream: "" },
];

function migration(script: string): Migration {
  const [version, name] = script.slice(1).replace(".sql", "").split("__");
  return { script, version: version.replaceAll("_", "."), description: name, type: "SQL", status: "PENDING", installed_on: "", installed_by: "", execution_time: 0 };
}
function script(name: string): Script {
  const [version, description] = name.slice(1).replace(".sql", "").split("__");
  return { name, kind: "versioned", version: version.replaceAll("_", "."), description, language: "sql", directory: "migrations", has_undo: false, change: "" };
}
function status(names: string[]): JobResult {
  return { success: true, error: null, current_version: null, migrations: names.map(migration), sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null };
}
function view(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}

let onDisk: string[];
let checkedOut: RepoStatus;
const onFeature = (): RepoStatus => (checkedOut = { ...main, branch: "feature/x", upstream: "" });

beforeEach(() => {
  onDisk = [A, B];
  runJob.mockReset();
  runJob.mockImplementation(async () => status(onDisk));
  scripts.listScripts.mockReset();
  scripts.listScripts.mockImplementation(async () => onDisk.map(script));
  scripts.readScript.mockReset();
  scripts.readScript.mockImplementation(async (_p: string, name: string) => ({ ...script(name), content: `-- ${name} on main\n` }));
  scripts.saveScript.mockReset();
  scripts.saveScript.mockResolvedValue(script(B));
  Object.values(git).forEach((mock) => mock.mockReset());
  checkedOut = main;
  git.getRepo.mockImplementation(async () => checkedOut);
  git.getBranches.mockResolvedValue(branches);
  git.switchBranch.mockImplementation(async () => onFeature());
});

async function switchToFeature() {
  await userEvent.click(await screen.findByRole("button", { name: "Branch main" }));
  await userEvent.click(await screen.findByRole("button", { name: "feature/x" }));
}

it("shows no branch chip outside a git repository", async () => {
  git.getRepo.mockImplementation(async () => ({ repository: false }));
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await waitFor(() => expect(git.getRepo).toHaveBeenCalledWith("p1"));

  expect(screen.queryByRole("button", { name: /^Branch/ })).not.toBeInTheDocument();
});

it("shows the branch chip in the header of a project in a repository", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  expect(await screen.findByRole("button", { name: "Branch main" })).toBeInTheDocument();
});

it("asks before switching over unsaved edits, then switches and reports the move", async () => {
  const onMoved = vi.fn();
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} onMoved={onMoved} />));
  await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");

  await switchToFeature();
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(git.switchBranch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));

  await waitFor(() => expect(git.switchBranch).toHaveBeenCalledWith("p1", "feature/x"));
  expect(await screen.findByRole("button", { name: "Branch feature/x" })).toBeInTheDocument();
  expect(onMoved).toHaveBeenCalledTimes(1);
});

it("locks the branch menu while the SQL preview is open", async () => {
  runJob.mockImplementation(async (_p: string, command: string) => (command === "preview" ? { ...status(onDisk), sql: [] } : status(onDisk)));
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  await screen.findByRole("region", { name: "SQL to be applied" });

  await userEvent.click(screen.getByRole("button", { name: "Branch main" }));
  const menu = screen.getByRole("dialog", { name: "Branch" });

  expect(await within(menu).findByRole("button", { name: "feature/x" })).toBeDisabled();
  expect(within(menu).getByRole("button", { name: "Fetch" })).toBeDisabled();
  expect(menu).toHaveTextContent("A database change is running.");
});

it("locks the branch menu while a database change runs", async () => {
  runJob.mockImplementation(async (_p: string, command: string) => {
    if (command === "migrate") {
      return new Promise(() => {});
    }
    return command === "preview" ? { ...status(onDisk), sql: [{ script: B, statements: ["CREATE TABLE orders (id INTEGER)"] }] } : status(onDisk);
  });
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  await userEvent.click(await screen.findByRole("button", { name: "Apply 1 migration" }));
  expect(screen.queryByRole("region", { name: "SQL to be applied" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Branch main" }));
  const menu = screen.getByRole("dialog", { name: "Branch" });

  expect(await within(menu).findByRole("button", { name: "feature/x" })).toBeDisabled();
  expect(menu).toHaveTextContent("A database change is running.");
});

it("closes the editor when the open script is not on the new branch", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
  await screen.findByLabelText(`Content of ${B}`);
  git.switchBranch.mockImplementation(async () => {
    onDisk = [A];
    return onFeature();
  });

  await switchToFeature();

  await waitFor(() => expect(screen.queryByLabelText(`Content of ${B}`)).not.toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("reads the open script again from the new branch", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
  expect(await screen.findByLabelText(`Content of ${B}`)).toHaveValue(`-- ${B} on main\n`);
  scripts.readScript.mockImplementation(async (_p: string, name: string) => ({ ...script(name), content: `-- ${name} on feature/x\n` }));

  await switchToFeature();

  await waitFor(() => expect(screen.getByLabelText(`Content of ${B}`)).toHaveValue(`-- ${B} on feature/x\n`));
});

it("shows a refusal under the chip and keeps the branch", async () => {
  git.switchBranch.mockRejectedValue(new Error("Your local changes to dblift.yaml would be overwritten by switching. Commit them first."));
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));

  await switchToFeature();

  expect(await screen.findByRole("alert")).toHaveTextContent("would be overwritten");
  expect(screen.getByRole("button", { name: "Branch main" })).toBeInTheDocument();
});

it("reads the git status again after a script is saved", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");
  await waitFor(() => expect(git.getRepo).toHaveBeenCalledTimes(1));

  await userEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(git.getRepo).toHaveBeenCalledTimes(2));
});

it("fetches and pushes without asking about unsaved edits", async () => {
  git.fetchRepo.mockImplementation(async () => (checkedOut = { ...main, behind: 1 }));
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");

  await userEvent.click(screen.getByRole("button", { name: "Branch main" }));
  await userEvent.click(await screen.findByRole("button", { name: "Fetch" }));

  await waitFor(() => expect(git.fetchRepo).toHaveBeenCalledWith("p1"));
  expect(screen.queryByText("Discard your changes?")).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Branch main" })).toHaveTextContent("↓1");
});

describe("committing", () => {
  const changedFiles: RepoStatus["files"] = [
    { path: `migrations/${B}`, state: "modified" },
    { path: "dblift.yaml", state: "modified" },
    { path: "notes.txt", state: "untracked" },
  ];

  beforeEach(() => {
    checkedOut = { ...main, files: changedFiles };
    scripts.listScripts.mockImplementation(async () => onDisk.map((name) => ({ ...script(name), change: checkedOut.files?.some((f) => f.path === `migrations/${name}`) ? "modified" : "" })));
    git.commitFiles.mockImplementation(async () => (checkedOut = { ...main, files: [{ path: "notes.txt", state: "untracked" }], ahead: 1 }));
  });

  async function openCommit() {
    render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
    await screen.findByRole("table", { name: "Migrations" });
    await waitFor(() => expect(screen.getByText("Uncommitted")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Branch main" }));
    await userEvent.click(await screen.findByRole("button", { name: "Commit…" }));
    return screen.getByRole("dialog", { name: "Commit" });
  }

  it("marks the uncommitted migration in the grid", async () => {
    render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
    const grid = await screen.findByRole("table", { name: "Migrations" });

    await waitFor(() => expect(within(grid).getByRole("row", { name: /create orders/ })).toHaveTextContent("Uncommitted"));
    expect(within(grid).getByRole("row", { name: /create customers/ })).not.toHaveTextContent("Uncommitted");
  });

  it("opens the commit with the project's changed scripts and its config ticked", async () => {
    const dialog = await openCommit();

    expect(within(dialog).getByRole("checkbox", { name: `migrations/${B}` })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "dblift.yaml" })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "notes.txt" })).not.toBeChecked();
  });

  // The script list holds migrations only; an undo script is known by its migration.
  describe("with a changed undo script", () => {
    const U = "U1_0_1__create_orders.sql";

    beforeEach(() => {
      checkedOut = { ...main, files: [...changedFiles, { path: `migrations/${U}`, state: "untracked" }] };
      scripts.listScripts.mockImplementation(async () =>
        onDisk.map((name) => ({ ...script(name), has_undo: name === B, change: name === B ? "untracked" : "" })),
      );
    });

    it("ticks it in the commit", async () => {
      const dialog = await openCommit();

      expect(within(dialog).getByRole("checkbox", { name: `migrations/${B}` })).toBeChecked();
      expect(within(dialog).getByRole("checkbox", { name: `migrations/${U}` })).toBeChecked();
    });

    it("offers its changes on the editor's undo tab", async () => {
      render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
      await userEvent.click(await screen.findByRole("button", { name: `Open ${B}` }));
      await userEvent.click(await screen.findByRole("tab", { name: "Undo script" }));

      expect(await screen.findByRole("button", { name: "Changes" })).toBeInTheDocument();
    });
  });

  it("commits, closes the dialog and reads the scripts again", async () => {
    const dialog = await openCommit();
    const reads = scripts.listScripts.mock.calls.length;
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Message" }), "Add orders");

    await userEvent.click(within(dialog).getByRole("button", { name: "Commit 2 files" }));

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Commit" })).not.toBeInTheDocument());
    expect(git.commitFiles).toHaveBeenCalledWith("p1", [`migrations/${B}`, "dblift.yaml"], "Add orders");
    await waitFor(() => expect(scripts.listScripts.mock.calls.length).toBeGreaterThan(reads));
    expect(await screen.findByRole("button", { name: "Branch main" })).toHaveTextContent("↑1");
    await waitFor(() => expect(screen.queryByText("Uncommitted")).not.toBeInTheDocument());
  });

  it("keeps the dialog open with the refusal shown there only", async () => {
    git.commitFiles.mockRejectedValue(new Error("Author identity unknown. Set user.name and user.email with your own git tool."));
    const dialog = await openCommit();
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Message" }), "Add orders");

    await userEvent.click(within(dialog).getByRole("button", { name: "Commit 2 files" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Author identity unknown");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(within(dialog).getByRole("textbox", { name: "Message" })).toHaveValue("Add orders");
  });
});
