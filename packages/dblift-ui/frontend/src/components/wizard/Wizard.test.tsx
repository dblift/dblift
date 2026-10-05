import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import type { RepoStatus } from "../../api/types";
import { onMain, project, U, V } from "../../test/wizard";
import { START, STEPS, type StepProps, type WizardStep } from "../../wizard/steps";
import Wizard from "./Wizard";

const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(), pullRequestLink: vi.fn(),
}));
vi.mock("../../api/git", () => git);

let repo: RepoStatus;
beforeEach(() => {
  Object.values(git).forEach((mock) => mock.mockReset());
  repo = onMain;
  git.getRepo.mockImplementation(async () => repo);
});

/** A step that is done once its own id is in the description; it has a field, to show its state is kept. */
function fake(id: string, title: string, available: WizardStep["available"] = () => true): WizardStep {
  function Component({ context, onNext, onBack, last }: StepProps) {
    const [note, setNote] = useState("");
    return (
      <div>
        <p>Body of {id}</p>
        <label>
          Note for {id}
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button onClick={onBack}>Back</button>
        <button onClick={() => context.update({ unsaved: true })}>Edit without saving</button>
        <button onClick={() => context.update({ scripts: { migration: V, undo: U } })}>Create the files</button>
        <button onClick={() => context.changed()}>Change a file</button>
        <button
          onClick={() => {
            context.update({ description: `${context.description} ${id}` });
            onNext();
          }}
        >
          {last ? "Finish" : "Next"}
        </button>
      </div>
    );
  }
  return { id, title, Component, available, done: (c) => c.description.split(" ").includes(id) };
}

const one = fake("one", "Describe");
const two = fake("two", "Write");
const three = fake("three", "Test");
const inRepo = fake("four", "Commit", (c) => c.repo?.repository === true);

function wizard(steps: WizardStep[] = [one, two, three]) {
  const onClose = vi.fn();
  const onChanged = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <button>Opener</button>
      <Wizard project={project} onClose={onClose} onChanged={onChanged} steps={steps} />
    </QueryClientProvider>,
  );
  return { onClose, onChanged };
}

const rail = () => within(screen.getByRole("navigation", { name: "Steps" }));
const next = () => userEvent.click(screen.getByRole("button", { name: "Next" }));

it("ships describe, write and test as its first steps", () => {
  expect(STEPS.slice(0, 3).map((s) => s.id)).toEqual(["describe", "write", "test"]);
  expect(STEPS.slice(0, 3).map((s) => s.title)).toEqual(["Describe", "Write", "Test"]);
});

it("ends with commit and publish, offered only in a git repository", () => {
  expect(STEPS.map((s) => s.id)).toEqual(["describe", "write", "test", "commit", "publish"]);
  expect(STEPS.map((s) => s.title)).toEqual(["Describe", "Write", "Test", "Commit", "Publish"]);
  const base = { ...START, project, update: () => {}, changed: () => {} };
  const inside = { ...base, repo: onMain };
  const outside = { ...base, repo: { repository: false } };
  expect(STEPS.filter((s) => s.available(inside)).map((s) => s.id)).toEqual(["describe", "write", "test", "commit", "publish"]);
  expect(STEPS.filter((s) => s.available(outside)).map((s) => s.id)).toEqual(["describe", "write", "test"]);
  expect(STEPS.filter((s) => s.available({ ...base, repo: undefined })).map((s) => s.id)).toEqual(["describe", "write", "test"]);
});

it("counts commit done once committed, and publish once published", () => {
  const base = { ...START, project, repo: onMain, update: () => {}, changed: () => {} };
  const [commit, publish] = STEPS.slice(3);
  expect(commit.done(base)).toBe(false);
  expect(commit.done({ ...base, committed: true })).toBe(true);
  expect(publish.done(base)).toBe(false);
  expect(publish.done({ ...base, published: true })).toBe(true);
});

it("is a dialog named New change, listing the steps in order with their numbers", () => {
  wizard();

  expect(screen.getByRole("dialog", { name: "New change" })).toBeInTheDocument();
  const items = rail().getAllByRole("listitem");
  expect(items.map((item) => item.textContent)).toEqual(["1Describe", "2Write", "3Test"]);
});

it("renders whatever the step list holds: an extra step is shown and reached like the others", async () => {
  wizard([one, two, three, fake("review", "Review")]);

  expect(rail().getAllByRole("listitem")).toHaveLength(4);
  expect(rail().getByRole("button", { name: "Review" })).toBeInTheDocument();
  await next();
  await next();
  await next();
  expect(screen.getByText("Body of review")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
});

it("shows only the steps available in the context", async () => {
  repo = { repository: false };
  wizard([one, two, three, inRepo]);
  await waitFor(() => expect(git.getRepo).toHaveBeenCalled());

  expect(rail().getAllByRole("listitem")).toHaveLength(3);
  expect(screen.getByText("Step 1 of 3 — Describe")).toBeInTheDocument();
});

it("adds a step that becomes available once the repository is read", async () => {
  wizard([one, two, three, inRepo]);

  expect(await rail().findByRole("button", { name: "Commit" })).toBeInTheDocument();
  expect(screen.getByText("Step 1 of 4 — Describe")).toBeInTheDocument();
});

it("marks the active step with aria-current=step, and moves it with Next", async () => {
  wizard();

  expect(rail().getByRole("button", { name: "Describe" })).toHaveAttribute("aria-current", "step");
  expect(rail().getByRole("button", { name: "Write" })).not.toHaveAttribute("aria-current");
  await next();
  expect(rail().getByRole("button", { name: "Write" })).toHaveAttribute("aria-current", "step");
  expect(screen.getByText("Body of two")).toBeVisible();
  expect(screen.queryByText("Body of one")).not.toBeVisible();
});

it("never lets a step be opened before the previous ones are done", async () => {
  wizard();

  expect(rail().getByRole("button", { name: "Write" })).toBeDisabled();
  expect(rail().getByRole("button", { name: "Test" })).toBeDisabled();
  await next();
  expect(rail().getByRole("button", { name: "Test" })).toBeDisabled();
});

it("marks the done steps in the list", async () => {
  wizard();

  await next();

  expect(rail().getByRole("button", { name: "Describe, done" })).toBeEnabled();
  expect(rail().getByRole("button", { name: "Write" })).toBeInTheDocument();
});

it("goes back with the step's Back and with the list, keeping what a visited step holds", async () => {
  wizard();
  await userEvent.type(screen.getByRole("textbox", { name: "Note for one" }), "kept");
  await next();

  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("textbox", { name: "Note for one" })).toHaveValue("kept");
  await userEvent.click(rail().getByRole("button", { name: "Write" }));
  expect(screen.getByText("Body of two")).toBeVisible();
  await userEvent.click(rail().getByRole("button", { name: "Describe, done" }));
  expect(screen.getByRole("textbox", { name: "Note for one" })).toHaveValue("kept");
});

it("puts focus on the heading of the step it moves to", async () => {
  wizard();

  await next();
  expect(screen.getByRole("heading", { name: "Write" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "Describe" })).toHaveFocus();
});

it("shows a compact line with the position, for narrow screens", async () => {
  wizard();

  expect(screen.getByText("Step 1 of 3 — Describe")).toBeInTheDocument();
  await next();
  expect(screen.getByText("Step 2 of 3 — Write")).toBeInTheDocument();
});

it("tells the last step it is last, and finishes when it moves on", async () => {
  const { onClose } = wizard();
  await next();
  await next();

  await userEvent.click(screen.getByRole("button", { name: "Finish" }));

  expect(onClose).toHaveBeenCalledTimes(1);
});

it("closes with Escape", async () => {
  const { onClose } = wizard();

  await userEvent.keyboard("{Escape}");

  expect(onClose).toHaveBeenCalledTimes(1);
});

it("closes with the Close button", async () => {
  const { onClose, onChanged } = wizard();

  await userEvent.click(screen.getByRole("button", { name: "Close" }));

  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onChanged).not.toHaveBeenCalled();
});

it("asks nothing on close once the files exist, and has the view behind read them", async () => {
  const { onClose, onChanged } = wizard();
  await userEvent.click(screen.getByRole("button", { name: "Create the files" }));

  await userEvent.click(screen.getByRole("button", { name: "Close" }));

  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("passes a step's changes on to the view behind", async () => {
  const { onChanged } = wizard();

  await userEvent.click(screen.getByRole("button", { name: "Change a file" }));

  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("asks before closing over unsaved edits", async () => {
  const { onClose } = wizard();
  await userEvent.click(screen.getByRole("button", { name: "Edit without saving" }));

  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.getByText("Discard the unsaved edits?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Keep editing" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.queryByText("Discard the unsaved edits?")).not.toBeInTheDocument();

  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("button", { name: "Discard and close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("keeps Tab inside the dialog's visible controls, skipping the hidden steps", async () => {
  wizard();
  await next();
  // Back on the first step: the second one stays in the page, hidden, after the visible controls.
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  const dialog = screen.getByRole("dialog", { name: "New change" });
  const last = within(dialog).getByRole("button", { name: "Next" });
  last.focus();

  await userEvent.tab();

  expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();
  await userEvent.tab({ shift: true });
  expect(last).toHaveFocus();
});
