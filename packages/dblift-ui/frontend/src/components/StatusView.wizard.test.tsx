import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { JobResult, Migration, Project, Script } from "../api/types";
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
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(), pullRequestLink: vi.fn(),
}));
vi.mock("../api/git", () => git);
vi.mock("../api/scratch", () => ({ getScratchPlan: vi.fn().mockResolvedValue({ strategy: "skip", engine: "", summary: "", warning: "" }) }));

const project: Project = {
  id: "p1", name: "shop-api", config_path: "/w/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null,
  missing: false, repository: "w", repository_path: "/w", flyway_table: null,
};
const A = "V1_0_0__create_customers.sql";
const C = "V1_0_1__add_invoices.sql";

function migration(script: string): Migration {
  const [version, name] = script.slice(1).replace(".sql", "").split("__");
  return { script, version: version.replaceAll("_", "."), description: name, type: "SQL", status: script === A ? "SUCCESS" : "PENDING", installed_on: "", installed_by: "", execution_time: 0 };
}
function script(name: string): Script {
  const [version, description] = name.slice(1).replace(".sql", "").split("__");
  return { name, kind: "versioned", version: version.replaceAll("_", "."), description, language: "sql", directory: "migrations", has_undo: true, path: "", change: "", undo_path: "", undo_change: "" };
}
function status(names: string[]): JobResult {
  return { success: true, error: null, current_version: null, migrations: names.map(migration), sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null, scratch: null };
}
function view(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}

let onDisk: string[];
beforeEach(() => {
  onDisk = [A];
  runJob.mockReset();
  runJob.mockImplementation(async () => status(onDisk));
  Object.values(scripts).forEach((mock) => mock.mockReset());
  scripts.listScripts.mockImplementation(async () => onDisk.map(script));
  scripts.readScript.mockImplementation(async (_p: string, name: string) => ({ ...script(name), content: `-- ${name}\n` }));
  scripts.createScripts.mockImplementation(async () => {
    onDisk = [A, C];
    return { created: [C, `U${C.slice(1)}`] };
  });
  Object.values(git).forEach((mock) => mock.mockReset());
  git.getRepo.mockResolvedValue({ repository: false });
});

const newChange = () => screen.getByRole("button", { name: "New change" });

it("offers New change in the command bar as a normal button: Migrate stays the only primary action", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  expect(newChange()).not.toHaveClass("button--primary");
  const bar = newChange().parentElement!;
  const primary = within(bar).getAllByRole("button").filter((button) => button.classList.contains("button--primary"));
  expect(primary.map((button) => button.textContent)).toEqual(["Migrate"]);
});

it("opens the wizard", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(newChange());

  expect(screen.getByRole("dialog", { name: "New change" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "What does this change do?" })).toHaveFocus();
});

it("asks before opening the wizard over unsaved edits", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: `Open ${A}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${A}`), "x");

  await userEvent.click(newChange());
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "New change" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(screen.getByRole("dialog", { name: "New change" })).toBeInTheDocument();
});

it("is disabled while a change runs", async () => {
  runJob.mockImplementation(async (_p: string, command: string) => (command === "undo" ? new Promise(() => {}) : status(onDisk)));
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  expect(newChange()).toBeEnabled();

  await userEvent.click(screen.getByRole("button", { name: "Undo last migration" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm undo" }));

  expect(newChange()).toBeDisabled();
});

it("has the view read the status and the scripts again once the files are created, and on close", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(newChange());
  const reads = runJob.mock.calls.length;
  const lists = scripts.listScripts.mock.calls.length;

  await userEvent.type(screen.getByRole("textbox", { name: "What does this change do?" }), "Add invoices");
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await screen.findByRole("region", { name: "Migration" });

  await waitFor(() => expect(runJob.mock.calls.length).toBeGreaterThan(reads));
  await waitFor(() => expect(scripts.listScripts.mock.calls.length).toBeGreaterThan(lists));
  const afterCreate = runJob.mock.calls.length;
  await userEvent.click(screen.getByRole("button", { name: "Close" }));

  expect(screen.queryByRole("dialog", { name: "New change" })).not.toBeInTheDocument();
  await waitFor(() => expect(runJob.mock.calls.length).toBeGreaterThan(afterCreate));
  expect(await screen.findByRole("button", { name: `Open ${C}` })).toBeInTheDocument();
});
