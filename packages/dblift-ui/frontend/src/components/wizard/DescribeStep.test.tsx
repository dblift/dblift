import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { RepoStatus } from "../../api/types";
import { onMain, renderStep, U, V } from "../../test/wizard";
import DescribeStep from "./DescribeStep";

const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(), pullRequestLink: vi.fn(),
}));
vi.mock("../../api/git", () => git);
const scripts = vi.hoisted(() => ({ listScripts: vi.fn(), readScript: vi.fn(), saveScript: vi.fn(), createScripts: vi.fn() }));
vi.mock("../../api/scripts", () => scripts);

const calls: string[] = [];
beforeEach(() => {
  calls.length = 0;
  Object.values(git).forEach((mock) => mock.mockReset());
  Object.values(scripts).forEach((mock) => mock.mockReset());
  git.getRepo.mockResolvedValue(onMain);
  git.createBranch.mockImplementation(async (_p: string, name: string) => {
    calls.push(`branch ${name}`);
    return { ...onMain, branch: name, upstream: "" };
  });
  scripts.createScripts.mockImplementation(async () => {
    calls.push("scripts");
    return { created: [V, U] };
  });
});

const describe_ = () => screen.getByRole("textbox", { name: "What does this change do?" });
const branchBox = () => screen.getByRole("checkbox", { name: "Create a branch" });
const branchName = () => screen.getByRole("textbox", { name: "Branch name" });
const next = () => screen.getByRole("button", { name: "Next" });
const on = (branch: string): RepoStatus => ({ ...onMain, branch });

it("asks what the change does, and needs an answer before going on", async () => {
  renderStep(DescribeStep, { repo: onMain });

  expect(describe_()).toBeRequired();
  expect(next()).toBeDisabled();
  await userEvent.type(describe_(), "   ");
  expect(next()).toBeDisabled();
  await userEvent.type(describe_(), "Add invoices");
  expect(next()).toBeEnabled();
});

it("offers a branch named after the description, following it until the name is edited", async () => {
  const { context } = renderStep(DescribeStep, { repo: onMain });

  expect(branchName()).toHaveValue("feature/change");
  await userEvent.type(describe_(), "Add invoices");
  expect(branchName()).toHaveValue("feature/add-invoices");
  expect(context().branch.name).toBe("feature/add-invoices");

  await userEvent.clear(branchName());
  await userEvent.type(branchName(), "feature/billing");
  await userEvent.type(describe_(), " table");
  expect(branchName()).toHaveValue("feature/billing");
  expect(context().description).toBe("Add invoices table");
});

it.each(["main", "master", "develop"])("ticks Create a branch by default on %s", (branch) => {
  renderStep(DescribeStep, { repo: on(branch) });

  expect(branchBox()).toBeChecked();
});

it("keeps a branch change that lands just before the description is typed", () => {
  const { context } = renderStep(DescribeStep, { repo: on("topic") });
  expect(branchBox()).not.toBeChecked();

  // The box's default arrives while the step still shows the earlier state: typing must not undo it.
  act(() => {
    context().update({ branch: { ...context().branch, create: true } });
    fireEvent.change(describe_(), { target: { value: "Add invoices" } });
  });

  expect(context().branch).toEqual({ create: true, name: "feature/add-invoices" });
  expect(branchBox()).toBeChecked();
});

it("leaves Create a branch unticked on another branch, and hides the name until it is ticked", async () => {
  renderStep(DescribeStep, { repo: on("feature/x") });

  expect(branchBox()).not.toBeChecked();
  expect(screen.queryByRole("textbox", { name: "Branch name" })).not.toBeInTheDocument();
  await userEvent.click(branchBox());
  expect(branchName()).toHaveValue("feature/change");
});

it("offers no branch outside a git repository", () => {
  renderStep(DescribeStep, { repo: { repository: false } });

  expect(screen.queryByRole("checkbox", { name: "Create a branch" })).not.toBeInTheDocument();
});

it("creates the branch first, then the migration and its undo script, stores their names and moves on", async () => {
  const { onNext, changed, context } = renderStep(DescribeStep, { repo: onMain });
  await userEvent.type(describe_(), "Add invoices{Enter}with their lines");

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(calls).toEqual(["branch feature/add-invoices-with-their-lines", "scripts"]);
  expect(git.createBranch).toHaveBeenCalledWith("p1", "feature/add-invoices-with-their-lines");
  // The file names come from the first line, the title of the change.
  expect(scripts.createScripts).toHaveBeenCalledWith("p1", { kind: "versioned", language: "sql", description: "Add invoices" });
  expect(context().scripts).toEqual({ migration: V, undo: U });
  expect(context().description).toBe("Add invoices\nwith their lines");
  expect(changed).toHaveBeenCalled();
});

it("creates no branch when the box is unticked", async () => {
  const { onNext } = renderStep(DescribeStep, { repo: onMain });
  await userEvent.type(describe_(), "Add invoices");
  await userEvent.click(branchBox());

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(git.createBranch).not.toHaveBeenCalled();
  expect(calls).toEqual(["scripts"]);
});

it("creates only the scripts outside a git repository", async () => {
  const { onNext } = renderStep(DescribeStep, { repo: { repository: false } });
  await userEvent.type(describe_(), "Add invoices");

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(git.createBranch).not.toHaveBeenCalled();
  expect(scripts.createScripts).toHaveBeenCalledTimes(1);
});

it("shows a refused branch and stays, creating nothing", async () => {
  git.createBranch.mockRejectedValue(new Error("a branch named 'feature/add-invoices' already exists"));
  const { onNext, context } = renderStep(DescribeStep, { repo: onMain });
  await userEvent.type(describe_(), "Add invoices");

  await userEvent.click(next());

  expect(await screen.findByRole("alert")).toHaveTextContent("a branch named 'feature/add-invoices' already exists");
  expect(scripts.createScripts).not.toHaveBeenCalled();
  expect(onNext).not.toHaveBeenCalled();
  expect(context().scripts).toBeNull();
  expect(next()).toBeEnabled();
});

it("says the branch was made when the scripts are refused after it, and does not make it twice on a retry", async () => {
  scripts.createScripts.mockRejectedValueOnce(new Error("cannot create the migrations directory: Permission denied"));
  const { onNext } = renderStep(DescribeStep, { repo: onMain });
  await userEvent.type(describe_(), "Add invoices");

  await userEvent.click(next());

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("The branch feature/add-invoices was created, but the scripts were not");
  expect(alert).toHaveTextContent("Permission denied");
  expect(onNext).not.toHaveBeenCalled();
  expect(branchBox()).toBeDisabled();

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(git.createBranch).toHaveBeenCalledTimes(1);
  expect(scripts.createScripts).toHaveBeenCalledTimes(2);
});

it("cannot go on twice while it works", async () => {
  let finish: (value: { created: string[] }) => void = () => {};
  scripts.createScripts.mockImplementation(() => new Promise((resolve) => (finish = resolve)));
  renderStep(DescribeStep, { repo: { repository: false } });
  await userEvent.type(describe_(), "Add invoices");

  await userEvent.click(next());

  expect(next()).toBeDisabled();
  finish({ created: [V, U] });
  await waitFor(() => expect(next()).toBeEnabled());
});

it("creates nothing again when the scripts exist: the fields are read-only and the names shown", async () => {
  const { onNext } = renderStep(DescribeStep, {
    repo: on("feature/add-invoices"),
    data: { description: "Add invoices", branch: { create: true, name: "feature/add-invoices" }, scripts: { migration: V, undo: U } },
  });

  expect(describe_()).toHaveAttribute("readonly");
  expect(branchBox()).toBeDisabled();
  expect(branchName()).toHaveAttribute("readonly");
  expect(screen.getByText(V)).toBeInTheDocument();
  expect(screen.getByText(U)).toBeInTheDocument();

  await userEvent.click(next());

  expect(onNext).toHaveBeenCalledTimes(1);
  expect(git.createBranch).not.toHaveBeenCalled();
  expect(scripts.createScripts).not.toHaveBeenCalled();
});
