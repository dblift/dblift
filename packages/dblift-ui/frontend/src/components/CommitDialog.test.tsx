import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ChangedFile } from "../api/types";
import CommitDialog from "./CommitDialog";

const V = "migrations/V1_0_2__add_phone.sql";
const U = "migrations/U1_0_2__add_phone.sql";
const files: ChangedFile[] = [
  { path: V, state: "untracked" },
  { path: U, state: "untracked" },
  { path: "dblift.yaml", state: "modified" },
  { path: "notes.txt", state: "modified" },
];

function dialog(overrides: Partial<Parameters<typeof CommitDialog>[0]> = {}) {
  const props = { files, preselected: [V, U], busy: false, error: null, onCommit: vi.fn(), onClose: vi.fn(), ...overrides };
  const view = render(<CommitDialog {...props} />);
  return { props, view };
}
const box = (path: string) => screen.getByRole("checkbox", { name: path });
const commit = () => screen.getByRole("button", { name: /^Commit \d+ files?$/ });

it("is a dialog named Commit listing every changed file with its state", () => {
  dialog();

  const box_ = screen.getByRole("dialog", { name: "Commit" });
  const items = within(box_).getAllByRole("listitem");
  expect(items).toHaveLength(4);
  expect(items[0]).toHaveTextContent(V);
  expect(items[0]).toHaveTextContent("untracked");
  expect(items[2]).toHaveTextContent("dblift.yaml");
  expect(items[2]).toHaveTextContent("modified");
  files.forEach((file) => expect(box(file.path)).toBeInTheDocument());
});

it("ticks the preselected files only", () => {
  dialog();

  expect(box(V)).toBeChecked();
  expect(box(U)).toBeChecked();
  expect(box("dblift.yaml")).not.toBeChecked();
  expect(box("notes.txt")).not.toBeChecked();
});

it("selects all and none", async () => {
  dialog();

  await userEvent.click(screen.getByRole("button", { name: "Select all" }));
  files.forEach((file) => expect(box(file.path)).toBeChecked());
  await userEvent.click(screen.getByRole("button", { name: "Select none" }));
  files.forEach((file) => expect(box(file.path)).not.toBeChecked());
});

it("asks for a message whose first line is the summary", () => {
  dialog();

  const message = screen.getByRole("textbox", { name: "Message" });
  expect(message).toBeRequired();
  expect(screen.getByRole("dialog", { name: "Commit" })).toHaveTextContent(/first line is the summary/i);
});

it("commits the ticked files with the message", async () => {
  const { props } = dialog();
  await userEvent.click(box("dblift.yaml"));
  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Add phone{Enter}{Enter}With its undo script.");

  await userEvent.click(screen.getByRole("button", { name: "Commit 3 files" }));

  expect(props.onCommit).toHaveBeenCalledWith([V, U, "dblift.yaml"], "Add phone\n\nWith its undo script.");
});

it("counts one file in the singular", async () => {
  dialog({ preselected: [V] });
  expect(screen.getByRole("button", { name: "Commit 1 file" })).toBeInTheDocument();
});

it("cannot commit without a file or without a message", async () => {
  dialog({ preselected: [] });
  expect(commit()).toBeDisabled();

  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Add phone");
  expect(commit()).toBeDisabled();
  await userEvent.click(box(V));
  expect(commit()).toBeEnabled();

  await userEvent.clear(screen.getByRole("textbox", { name: "Message" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "   ");
  expect(commit()).toBeDisabled();
});

it("cannot commit while busy", async () => {
  dialog({ busy: true });
  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Add phone");

  expect(commit()).toBeDisabled();
});

it("does not let a conflicted file be ticked, and says to resolve it with another tool", async () => {
  dialog({ files: [...files, { path: "migrations/V1_0_1__orders.sql", state: "conflicted" }], preselected: [V, "migrations/V1_0_1__orders.sql"] });

  const conflicted = box("migrations/V1_0_1__orders.sql");
  expect(conflicted).toBeDisabled();
  expect(conflicted).not.toBeChecked();
  expect(conflicted.closest("li")).toHaveTextContent("resolve with your own tool");
  await userEvent.click(screen.getByRole("button", { name: "Select all" }));
  expect(conflicted).not.toBeChecked();
  expect(screen.getByRole("button", { name: /^Commit 4 files$/ })).toBeInTheDocument();
});

it("shows a refusal and keeps the selection and the message", async () => {
  const { props, view } = dialog();
  await userEvent.click(box("notes.txt"));
  await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "Add phone");

  view.rerender(<CommitDialog {...props} error="Author identity unknown. Set user.name and user.email with your own git tool." />);

  expect(screen.getByRole("alert")).toHaveTextContent("Author identity unknown");
  expect(screen.getByRole("dialog", { name: "Commit" })).toBeInTheDocument();
  expect(box("notes.txt")).toBeChecked();
  expect(box(V)).toBeChecked();
  expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Add phone");
});

it("says when the list of changed files is incomplete", () => {
  dialog({ truncated: true });
  expect(screen.getByRole("dialog", { name: "Commit" })).toHaveTextContent(/list is incomplete/i);
});

it("says nothing about completeness otherwise", () => {
  dialog();
  expect(screen.getByRole("dialog", { name: "Commit" })).not.toHaveTextContent(/incomplete/i);
});

it("closes on Close and on Escape", async () => {
  const { props } = dialog();

  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  await userEvent.keyboard("{Escape}");

  expect(props.onClose).toHaveBeenCalledTimes(2);
});
