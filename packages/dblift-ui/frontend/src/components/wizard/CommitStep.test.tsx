import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { RepoStatus, Script } from "../../api/types";
import { onMain, renderStep, U, V } from "../../test/wizard";
import CommitStep from "./CommitStep";

const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(), pullRequestLink: vi.fn(),
}));
vi.mock("../../api/git", () => git);
const scripts = vi.hoisted(() => ({ listScripts: vi.fn(), readScript: vi.fn(), saveScript: vi.fn(), createScripts: vi.fn() }));
vi.mock("../../api/scripts", () => scripts);

const OTHER = "V1_0_1__add_phone.sql";
// The project lives in a sub-folder of the repository: only the scripts list knows the exact paths.
const pathOf = (name: string) => `db/migrations/${name}`;
function script(name: string, change: string): Script {
  return {
    name, kind: "versioned", version: "1.0.2", description: "", language: "sql", directory: "migrations", has_undo: true,
    path: pathOf(name), change, undo_path: pathOf(`U${name.slice(1)}`), undo_change: change,
  };
}
const repo: RepoStatus = {
  ...onMain, branch: "feature/add-invoices", upstream: "",
  files: [
    { path: "db/dblift.yaml", state: "modified" },
    { path: pathOf(OTHER), state: "modified" },
    { path: pathOf(U), state: "untracked" },
    { path: pathOf(V), state: "untracked" },
    { path: "notes.txt", state: "modified" },
  ],
};
const ready = {
  description: "Add invoices\n\nWith their lines.", scripts: { migration: V, undo: U }, written: true,
  test: { outcome: "passed" as const, result: null },
};

beforeEach(() => {
  Object.values(git).forEach((mock) => mock.mockReset());
  Object.values(scripts).forEach((mock) => mock.mockReset());
  git.getRepo.mockResolvedValue(repo);
  git.commitFiles.mockResolvedValue({ ...repo, files: repo.files!.filter((f) => !f.path.includes("1_0_2")), ahead: 1 });
  scripts.listScripts.mockResolvedValue([script(OTHER, "modified"), script(V, "untracked")]);
});

const box = (path: string) => screen.getByRole("checkbox", { name: path });
const commitButton = () => screen.getByRole("button", { name: /^Commit \d+ files?$/ });

it("lists the repository's changed files with the wizard's two scripts ticked, by their exact paths", async () => {
  renderStep(CommitStep, { data: ready, repo });

  await waitFor(() => expect(box(pathOf(V))).toBeChecked());
  expect(box(pathOf(U))).toBeChecked();
  expect(box(pathOf(OTHER))).not.toBeChecked();
  expect(box("db/dblift.yaml")).not.toBeChecked();
  expect(box("notes.txt")).not.toBeChecked();
  expect(commitButton()).toHaveTextContent("Commit 2 files");
});

it("fills the message with the title", async () => {
  renderStep(CommitStep, { data: ready, repo });

  expect(await screen.findByRole("textbox", { name: "Message" })).toHaveValue("Add invoices");
});

it("commits the ticked files with the message, then shows the commit as done", async () => {
  const { context, changed, onNext } = renderStep(CommitStep, { data: ready, repo });
  await waitFor(() => expect(box(pathOf(V))).toBeChecked());
  await userEvent.click(box("notes.txt"));

  await userEvent.click(commitButton());

  await waitFor(() => expect(context().committed).toBe(true));
  expect(git.commitFiles).toHaveBeenCalledWith("p1", [pathOf(U), pathOf(V), "notes.txt"], "Add invoices");
  expect(changed).toHaveBeenCalled();
  expect(screen.getByText("The scripts are committed on feature/add-invoices.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^Commit/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(onNext).toHaveBeenCalledTimes(1);
});

it("commits nothing until Commit is clicked", async () => {
  renderStep(CommitStep, { data: ready, repo });
  await waitFor(() => expect(box(pathOf(V))).toBeChecked());

  expect(git.commitFiles).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
});

it("shows a refused commit and loses nothing", async () => {
  git.commitFiles.mockRejectedValue(new Error("Please tell me who you are."));
  const { context } = renderStep(CommitStep, { data: ready, repo });
  await waitFor(() => expect(box(pathOf(V))).toBeChecked());
  const message = screen.getByRole("textbox", { name: "Message" });
  await userEvent.type(message, " table");

  await userEvent.click(commitButton());

  expect(await screen.findByRole("alert")).toHaveTextContent("Please tell me who you are.");
  expect(context().committed).toBe(false);
  expect(message).toHaveValue("Add invoices table");
  expect(box(pathOf(V))).toBeChecked();
  expect(box(pathOf(U))).toBeChecked();
  expect(commitButton()).toBeEnabled();
});

it("warns when the scratch test failed", async () => {
  renderStep(CommitStep, { data: { ...ready, test: { outcome: "failed", result: null } }, repo });

  expect(await screen.findByText("The scratch test failed.")).toBeInTheDocument();
});

it("does not warn when the test passed or was skipped", async () => {
  renderStep(CommitStep, { data: { ...ready, test: { outcome: "skipped", result: null } }, repo });
  await waitFor(() => expect(box(pathOf(V))).toBeChecked());

  expect(screen.queryByText("The scratch test failed.")).not.toBeInTheDocument();
});

it("ticks the scripts once the scripts list arrives after the step opened", async () => {
  let answer: (list: Script[]) => void = () => {};
  scripts.listScripts.mockImplementation(() => new Promise((resolve) => (answer = resolve)));
  renderStep(CommitStep, { data: ready, repo });
  await waitFor(() => expect(scripts.listScripts).toHaveBeenCalled());
  expect(box(pathOf(V))).not.toBeChecked();

  answer([script(V, "untracked")]);

  await waitFor(() => expect(box(pathOf(V))).toBeChecked());
  expect(box(pathOf(U))).toBeChecked();
});

it("shows the commit as done when coming back to it", () => {
  renderStep(CommitStep, { data: { ...ready, committed: true }, repo: { ...repo, files: [] } });

  expect(screen.getByText("The scripts are committed on feature/add-invoices.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
});

it("says when the scripts have nothing left to commit, and lets the developer go on", async () => {
  scripts.listScripts.mockResolvedValue([script(V, "")]);
  const { context, onNext } = renderStep(CommitStep, { data: ready, repo: { ...repo, files: [{ path: "notes.txt", state: "modified" }] } });

  expect(await screen.findByText("The two scripts have nothing left to commit.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));

  expect(context().committed).toBe(true);
  expect(onNext).toHaveBeenCalledTimes(1);
  expect(git.commitFiles).not.toHaveBeenCalled();
});

it("goes back", async () => {
  const { onBack } = renderStep(CommitStep, { data: ready, repo });
  await waitFor(() => expect(box(pathOf(V))).toBeChecked());

  await userEvent.click(screen.getByRole("button", { name: "Back" }));

  expect(onBack).toHaveBeenCalledTimes(1);
});
