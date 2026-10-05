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

const project: Project = {
  id: "p1", name: "shop-api", config_path: "/w/dblift.yaml", last_environment: "", environments: [], engine: "sqlite", error: null,
  missing: false, repository: "w", repository_path: "/w", flyway_table: null,
};
const A = "V1_0_0__create_customers.sql";
const B = "V1_0_1__create_orders.sql";
const C = "V1_0_2__add_invoices.sql";

function migration(script: string, status: string): Migration {
  const [version, name] = script.slice(1).replace(".sql", "").split("__");
  return { script, version: version.replaceAll("_", "."), description: name, type: "SQL", status, installed_on: "", installed_by: "", execution_time: 0 };
}
function script(name: string, hasUndo: boolean): Script {
  const [version, description] = name.slice(1).replace(".sql", "").split("__");
  return { name, kind: "versioned", version: version.replaceAll("_", "."), description, language: "sql", directory: "migrations", has_undo: hasUndo, change: "" };
}
function status(migrations: Migration[]): JobResult {
  return { success: true, error: null, current_version: "1.0.0", migrations, sql: [], repaired: null, baseline_version: null, job_id: "j1", has_log: false, message: null };
}
function view(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>;
}

let onDisk: string[];

beforeEach(() => {
  onDisk = [A, B];
  runJob.mockReset();
  runJob.mockImplementation(async () => status(onDisk.map((name) => migration(name, name === A ? "SUCCESS" : "PENDING"))));
  scripts.listScripts.mockReset();
  scripts.listScripts.mockImplementation(async () => onDisk.map((name) => script(name, name !== B)));
  scripts.readScript.mockReset();
  scripts.readScript.mockImplementation(async (_p: string, name: string) => ({ ...script(name, true), content: `-- ${name}\n` }));
  scripts.saveScript.mockReset();
  scripts.saveScript.mockResolvedValue(script(A, true));
  scripts.createScripts.mockReset();
});

it("shows which migrations have an undo script", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  const grid = await screen.findByRole("table", { name: "Migrations" });

  await waitFor(() => expect(within(grid).getByRole("row", { name: /create customers/ })).toHaveTextContent("Yes"));
  expect(within(grid).getByRole("row", { name: /create orders/ })).not.toHaveTextContent("Yes");
});

it("opens a migration in the editor and re-reads the status after a save", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: `Open ${B}` }));
  const editor = await screen.findByLabelText(`Content of ${B}`);
  expect(editor).toHaveValue(`-- ${B}\n`);
  expect(screen.queryByRole("note")).not.toBeInTheDocument();

  const reads = runJob.mock.calls.length;
  await userEvent.type(editor, "SELECT 1;");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(scripts.saveScript).toHaveBeenCalledWith("p1", B, `-- ${B}\nSELECT 1;`));
  await waitFor(() => expect(runJob.mock.calls.length).toBe(reads + 1));
});

it("warns when the opened migration is already applied", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: `Open ${A}` }));

  await screen.findByLabelText(`Content of ${A}`);
  expect(screen.getByRole("note")).toHaveTextContent(/already applied/i);
});

it("creates a migration, lists it and opens it", async () => {
  scripts.createScripts.mockImplementation(async () => {
    onDisk = [A, B, C];
    return { created: [C, "U1_0_2__add_invoices.sql"] };
  });
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });

  await userEvent.click(screen.getByRole("button", { name: "New migration" }));
  await userEvent.type(screen.getByLabelText("What does it change?"), "add invoices");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));

  expect(await screen.findByLabelText(`Content of ${C}`)).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: `Open ${C}` })).toBeInTheDocument();
  expect(screen.queryByLabelText("What does it change?")).not.toBeInTheDocument();
});

it("closes the editor", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: `Open ${B}` }));
  await screen.findByLabelText(`Content of ${B}`);

  await userEvent.click(screen.getByRole("button", { name: "Close editor" }));

  expect(screen.queryByLabelText(`Content of ${B}`)).not.toBeInTheDocument();
});

it("asks before opening another migration over unsaved edits", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");

  await userEvent.click(screen.getByRole("button", { name: `Open ${A}` }));
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByLabelText(`Content of ${B}`)).toHaveValue(`-- ${B}\nx`);

  await userEvent.click(screen.getByRole("button", { name: `Open ${A}` }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(await screen.findByLabelText(`Content of ${A}`)).toHaveValue(`-- ${A}\n`);
  expect(screen.queryByLabelText(`Content of ${B}`)).not.toBeInTheDocument();
});

it("asks before starting a new migration over unsaved edits", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");

  await userEvent.click(screen.getByRole("button", { name: "New migration" }));
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.queryByLabelText("What does it change?")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(screen.getByLabelText("What does it change?")).toBeInTheDocument();
  expect(screen.queryByLabelText(`Content of ${B}`)).not.toBeInTheDocument();
});

it("locks saving and creating while the SQL preview is open", async () => {
  render(view(<StatusView project={project} onEnvironmentChange={() => {}} />));
  await screen.findByRole("table", { name: "Migrations" });
  await userEvent.click(screen.getByRole("button", { name: `Open ${B}` }));
  await userEvent.type(await screen.findByLabelText(`Content of ${B}`), "x");
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

  await userEvent.click(screen.getByRole("button", { name: "Migrate" }));
  const preview = await screen.findByRole("region", { name: "SQL to be applied" });

  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByText(/Close the SQL preview before editing/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New migration" })).toBeDisabled();

  await userEvent.click(within(preview).getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  expect(screen.queryByText(/Close the SQL preview before editing/)).not.toBeInTheDocument();
});
