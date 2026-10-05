import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { Branch, RepoStatus } from "../api/types";
import BranchChip from "./BranchChip";

const repo = (overrides: Partial<RepoStatus> = {}): RepoStatus => ({
  repository: true, root: "/work/shop", branch: "main", detached: false, upstream: "origin/main",
  ahead: 0, behind: 0, files: [], truncated: false, ...overrides,
});
const twoChanged: RepoStatus["files"] = [
  { path: "migrations/V1_0_2__add_phone.sql", state: "untracked" },
  { path: "dblift.yaml", state: "modified" },
];
const branches: Branch[] = [
  { name: "main", current: true, remote: false, upstream: "origin/main" },
  { name: "feature/billing", current: false, remote: false, upstream: "" },
  { name: "origin/main", current: false, remote: true, upstream: "" },
  { name: "origin/feature/reporting", current: false, remote: true, upstream: "" },
];

function chip(overrides: Partial<Parameters<typeof BranchChip>[0]> = {}) {
  const props = {
    repo: repo(), busy: false, error: null, locked: false,
    loadBranches: vi.fn(async () => branches),
    onSwitch: vi.fn(), onCreate: vi.fn(), onFetch: vi.fn(), onPull: vi.fn(), onPush: vi.fn(), onCommit: vi.fn(), onDismissError: vi.fn(),
    ...overrides,
  };
  render(<BranchChip {...props} />);
  return props;
}

async function openMenu(name = "Branch main") {
  await userEvent.click(screen.getByRole("button", { name }));
  const menu = screen.getByRole("dialog", { name: "Branch" });
  await within(menu).findByRole("list", { name: "Local branches" });
  return menu;
}

it("is a button named after the branch, or after a detached HEAD", () => {
  chip();
  expect(screen.getByRole("button", { name: "Branch main" })).toHaveTextContent("main");
  chip({ repo: repo({ branch: "", detached: true, upstream: "" }) });
  expect(screen.getByRole("button", { name: "Branch detached" })).toHaveTextContent("detached");
});

it("shows the uncommitted files, ahead and behind counts only when they are not zero", () => {
  chip({ repo: repo({ files: twoChanged, ahead: 1, behind: 3 }) });
  const button = screen.getByRole("button", { name: "Branch main" });
  expect(button).toHaveTextContent("2 uncommitted");
  expect(button).toHaveTextContent("↑1");
  expect(button).toHaveTextContent("↓3");
  expect(button.querySelector(".branch__dot")).not.toBeNull();
});

it("shows only the branch when nothing is changed, ahead or behind", () => {
  chip();
  const button = screen.getByRole("button", { name: "Branch main" });
  expect(button).not.toHaveTextContent("uncommitted");
  expect(button).not.toHaveTextContent("↑");
  expect(button).not.toHaveTextContent("↓");
  expect(button.querySelector(".branch__dot")).toBeNull();
});

it("loads the branches when the menu opens, local ones first, remote ones labelled", async () => {
  const props = chip();
  expect(props.loadBranches).not.toHaveBeenCalled();

  const menu = await openMenu();

  expect(props.loadBranches).toHaveBeenCalledTimes(1);
  const local = within(menu).getByRole("list", { name: "Local branches" });
  const remote = within(menu).getByRole("list", { name: "Remote branches" });
  expect(within(local).getAllByRole("listitem").map((item) => item.textContent)).toEqual([expect.stringContaining("main"), "feature/billing"]);
  expect(within(remote).getAllByRole("listitem").map((item) => item.textContent)).toEqual(["origin/main", "origin/feature/reporting"]);
  expect(local.compareDocumentPosition(remote) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("marks the current branch and does not offer to switch to it", async () => {
  chip();
  const menu = await openMenu();
  const local = within(menu).getByRole("list", { name: "Local branches" });

  expect(within(local).queryByRole("button", { name: "main" })).not.toBeInTheDocument();
  const current = within(local).getAllByRole("listitem")[0];
  expect(current).toHaveTextContent("current");
  expect(current.querySelector("[aria-current='true']")).toHaveTextContent("main");
  expect(within(local).getByRole("button", { name: "feature/billing" })).toBeEnabled();
});

it("filters the list as the user types in the search field", async () => {
  chip();
  const menu = await openMenu();

  await userEvent.type(within(menu).getByRole("searchbox", { name: "Search branches" }), "REPORT");

  expect(within(menu).getByRole("button", { name: "origin/feature/reporting" })).toBeInTheDocument();
  expect(within(menu).queryByRole("button", { name: "feature/billing" })).not.toBeInTheDocument();
  expect(within(menu).queryByRole("button", { name: "origin/main" })).not.toBeInTheDocument();
});

it("switches to a clicked branch and closes the menu", async () => {
  const props = chip();
  const menu = await openMenu();

  await userEvent.click(within(menu).getByRole("button", { name: "origin/feature/reporting" }));

  expect(props.onSwitch).toHaveBeenCalledWith("origin/feature/reporting");
  expect(screen.queryByRole("dialog", { name: "Branch" })).not.toBeInTheDocument();
});

it("says that the uncommitted files come along when there are some", async () => {
  chip({ repo: repo({ files: twoChanged }) });
  const menu = await openMenu();
  expect(menu).toHaveTextContent("2 uncommitted files will come along if git allows it.");
});

it("says nothing about uncommitted files when there are none", async () => {
  chip();
  const menu = await openMenu();
  expect(menu).not.toHaveTextContent("will come along");
});

it("creates a branch from the name typed, never from an empty one", async () => {
  const props = chip();
  const menu = await openMenu();
  const create = within(menu).getByRole("button", { name: "Create" });
  expect(create).toBeDisabled();

  await userEvent.type(within(menu).getByRole("textbox", { name: "New branch" }), "feature/add-thing");
  expect(create).toBeEnabled();
  await userEvent.click(create);

  expect(props.onCreate).toHaveBeenCalledWith("feature/add-thing");
});

it("fetches, pulls and pushes, with the counts on the buttons", async () => {
  const props = chip({ repo: repo({ ahead: 1, behind: 2 }) });

  await userEvent.click(within(await openMenu()).getByRole("button", { name: "Fetch" }));
  expect(props.onFetch).toHaveBeenCalledTimes(1);
  await userEvent.click(within(await openMenu()).getByRole("button", { name: "Pull ↓2" }));
  expect(props.onPull).toHaveBeenCalledTimes(1);
  await userEvent.click(within(await openMenu()).getByRole("button", { name: "Push ↑1" }));
  expect(props.onPush).toHaveBeenCalledTimes(1);
});

it("offers no pull without an upstream, and publishes a branch that has none", async () => {
  const props = chip({ repo: repo({ branch: "feature/add-thing", upstream: "", ahead: 0 }) });
  const menu = await openMenu("Branch feature/add-thing");

  expect(within(menu).getByRole("button", { name: "Pull" })).toBeDisabled();
  expect(within(menu).queryByRole("button", { name: /^Push/ })).not.toBeInTheDocument();
  await userEvent.click(within(menu).getByRole("button", { name: "Publish branch" }));
  expect(props.onPush).toHaveBeenCalledTimes(1);
});

it("offers neither pull nor push on a detached HEAD", async () => {
  chip({ repo: repo({ branch: "", detached: true, upstream: "" }) });
  const menu = await openMenu("Branch detached");

  expect(within(menu).getByRole("button", { name: "Pull" })).toBeDisabled();
  expect(within(menu).getByRole("button", { name: "Publish branch" })).toBeDisabled();
});

it("offers to commit only when something is changed", async () => {
  chip();
  expect(within(await openMenu()).getByRole("button", { name: "Commit…" })).toBeDisabled();
});

it("opens the commit from the menu", async () => {
  const props = chip({ repo: repo({ files: twoChanged }) });
  const menu = await openMenu();

  await userEvent.click(within(menu).getByRole("button", { name: "Commit…" }));

  expect(props.onCommit).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog", { name: "Branch" })).not.toBeInTheDocument();
});

const changers = (menu: HTMLElement) => [
  within(menu).getByRole("button", { name: "feature/billing" }),
  within(menu).getByRole("button", { name: "origin/feature/reporting" }),
  within(menu).getByRole("button", { name: "Create" }),
  within(menu).getByRole("button", { name: "Fetch" }),
  within(menu).getByRole("button", { name: "Pull ↓1" }),
  within(menu).getByRole("button", { name: "Push ↑1" }),
  within(menu).getByRole("button", { name: "Commit…" }),
];

it("disables everything that changes something while an action runs", async () => {
  chip({ busy: true, repo: repo({ files: twoChanged, ahead: 1, behind: 1 }) });
  const menu = await openMenu();
  await userEvent.type(within(menu).getByRole("textbox", { name: "New branch" }), "x");

  changers(menu).forEach((button) => expect(button).toBeDisabled());
  expect(within(menu).getByRole("searchbox", { name: "Search branches" })).toBeEnabled();
});

it("disables everything that changes something while a database change runs, and says why", async () => {
  chip({ locked: true, repo: repo({ files: twoChanged, ahead: 1, behind: 1 }) });
  const menu = await openMenu();
  await userEvent.type(within(menu).getByRole("textbox", { name: "New branch" }), "x");

  changers(menu).forEach((button) => expect(button).toBeDisabled());
  expect(menu).toHaveTextContent("A database change is running.");
});

it("shows a failure under the chip until it is dismissed", async () => {
  const props = chip({ error: "This branch and its remote have both moved. Merge or rebase with your own git tool, then come back." });

  expect(screen.getByRole("alert")).toHaveTextContent("both moved");
  await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

  expect(props.onDismissError).toHaveBeenCalledTimes(1);
});

it("closes on Escape and gives the focus back to the chip", async () => {
  chip();
  await openMenu();
  expect(screen.getByRole("searchbox", { name: "Search branches" })).toHaveFocus();

  await userEvent.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "Branch" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Branch main" })).toHaveFocus();
});

it("closes on a click outside", async () => {
  render(<p>Elsewhere</p>);
  chip();
  await openMenu();

  await userEvent.click(screen.getByText("Elsewhere"));

  expect(screen.queryByRole("dialog", { name: "Branch" })).not.toBeInTheDocument();
});

it("is operable with the keyboard alone", async () => {
  const props = chip();
  screen.getByRole("button", { name: "Branch main" }).focus();

  await userEvent.keyboard("{Enter}");
  await waitFor(() => expect(screen.getByRole("button", { name: "feature/billing" })).toBeInTheDocument());
  await userEvent.tab();
  expect(screen.getByRole("button", { name: "feature/billing" })).toHaveFocus();
  await userEvent.keyboard("{Enter}");

  expect(props.onSwitch).toHaveBeenCalledWith("feature/billing");
  expect(screen.getByRole("button", { name: "Branch main" })).toHaveFocus();
});

it("says why the branches could not be read", async () => {
  chip({ loadBranches: vi.fn(async () => Promise.reject(new Error("git is not installed"))) });
  await userEvent.click(screen.getByRole("button", { name: "Branch main" }));

  expect(await within(screen.getByRole("dialog", { name: "Branch" })).findByText(/git is not installed/)).toBeInTheDocument();
});
