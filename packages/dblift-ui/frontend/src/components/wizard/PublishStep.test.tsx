import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { RepoStatus, ScratchResult } from "../../api/types";
import { onMain, renderStep, U, V } from "../../test/wizard";
import PublishStep from "./PublishStep";

const git = vi.hoisted(() => ({
  getRepo: vi.fn(), getBranches: vi.fn(), switchBranch: vi.fn(), createBranch: vi.fn(), fetchRepo: vi.fn(),
  pullRepo: vi.fn(), pushRepo: vi.fn(), commitFiles: vi.fn(), scriptDiff: vi.fn(), pullRequestLink: vi.fn(),
}));
vi.mock("../../api/git", () => git);

const BRANCH = "feature/add-invoices";
const local: RepoStatus = { ...onMain, branch: BRANCH, upstream: "", ahead: 0 };
const pushed: RepoStatus = { ...local, upstream: `origin/${BRANCH}` };
const URL_ = "https://github.com/acme/shop/compare/feature/add-invoices?expand=1&title=Add%20invoices&body=x";
const passed: ScratchResult = {
  strategy: "file", passed: true, skipped: false, script: V,
  phases: [{ name: "build", ok: true, detail: "" }, { name: "undo", ok: true, detail: "" }, { name: "reapply", ok: true, detail: "" }],
};
const done = {
  description: "Add invoices", scripts: { migration: V, undo: U }, written: true, committed: true,
  test: { outcome: "passed" as const, result: passed },
};
const BODY = `## Change\nAdd invoices\n\n## Scripts\n- ${V}\n- ${U}\n\n## Scratch test\nPassed on a temporary SQLite database: build from zero, undo, re-apply.\n`;

beforeEach(() => {
  Object.values(git).forEach((mock) => mock.mockReset());
  git.getRepo.mockResolvedValue(local);
  git.pushRepo.mockResolvedValue(pushed);
  git.pullRequestLink.mockResolvedValue({ url: URL_, kind: "github", branch: BRANCH });
});

const publish = () => screen.getByRole("button", { name: "Publish branch" });

it("shows the branch, and pushes nothing before a click", () => {
  renderStep(PublishStep, { data: done, repo: local, last: true });

  expect(screen.getByText(BRANCH)).toBeInTheDocument();
  expect(publish()).toBeEnabled();
  expect(git.pushRepo).not.toHaveBeenCalled();
  expect(git.pullRequestLink).not.toHaveBeenCalled();
});

it("offers Push for a branch that has an upstream", () => {
  renderStep(PublishStep, { data: done, repo: { ...pushed, ahead: 1 }, last: true });

  expect(screen.getByRole("button", { name: "Push" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Publish branch" })).not.toBeInTheDocument();
});

it("pushes on click, then offers the pull request page the server built, in a new tab", async () => {
  const { context, changed } = renderStep(PublishStep, { data: done, repo: local, last: true });

  await userEvent.click(publish());

  const link = await screen.findByRole("link", { name: "Open the pull request page" });
  expect(git.pushRepo).toHaveBeenCalledWith("p1");
  expect(git.pullRequestLink).toHaveBeenCalledWith("p1", "Add invoices", BODY);
  expect(link).toHaveAttribute("href", URL_);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(context().published).toBe(true);
  expect(changed).toHaveBeenCalled();
  // The text is shown for review.
  expect(screen.getByRole("textbox", { name: "Pull request title" })).toHaveValue("Add invoices");
  expect(screen.getByRole("textbox", { name: "Pull request description" })).toHaveValue(BODY);
  expect(screen.getByRole("textbox", { name: "Pull request description" })).toHaveAttribute("readonly");
});

it.each(["http://github.com/acme/shop/compare/x", "javascript:alert(1)", "//evil.example/x", " https://github.com/x"])(
  "never links to an address that is not https: %s",
  async (url) => {
    git.pullRequestLink.mockResolvedValue({ url, kind: "github", branch: BRANCH });
    renderStep(PublishStep, { data: done, repo: local, last: true });

    await userEvent.click(publish());

    expect(await screen.findByRole("button", { name: "Copy the title" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  },
);

it("gives the text to copy, and where to paste it, when the host is unknown", async () => {
  git.pullRequestLink.mockResolvedValue({ url: null, kind: null, branch: BRANCH });
  const user = userEvent.setup();
  renderStep(PublishStep, { data: done, repo: local, last: true });

  await user.click(publish());

  expect(await screen.findByText(`Open a pull request for ${BRANCH} on your git host, then paste the title and the description there.`)).toBeInTheDocument();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Pull request title" })).toHaveAttribute("readonly");
  expect(screen.getByRole("textbox", { name: "Pull request description" })).toHaveValue(BODY);

  await user.click(screen.getByRole("button", { name: "Copy the title" }));
  expect(await navigator.clipboard.readText()).toBe("Add invoices");
  expect(screen.getByRole("status")).toHaveTextContent("Copied.");
  await user.click(screen.getByRole("button", { name: "Copy the description" }));
  expect(await navigator.clipboard.readText()).toBe(BODY);
});

it("shows the whole description, down to the test's result, without scrolling", async () => {
  const long = { ...done, description: "Add invoices\n\nInvoices are kept per customer.\nTotals are in cents.\nOne currency per invoice." };
  renderStep(PublishStep, { data: long, repo: local, last: true });

  await userEvent.click(publish());

  const body = await screen.findByRole("textbox", { name: "Pull request description" });
  const lines = (body as HTMLTextAreaElement).value.split("\n").length;
  expect(Number(body.getAttribute("rows"))).toBeGreaterThanOrEqual(lines);
});

it("tells the developer to copy by hand when the clipboard refuses", async () => {
  git.pullRequestLink.mockResolvedValue({ url: null, kind: null, branch: BRANCH });
  const user = userEvent.setup();
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
  renderStep(PublishStep, { data: done, repo: local, last: true });
  await user.click(publish());

  await user.click(await screen.findByRole("button", { name: "Copy the title" }));

  expect(screen.getByRole("status")).toHaveTextContent("Select the text and copy it with the keyboard.");
});

it("says a failed scratch test failed in the description", async () => {
  const failed: ScratchResult = { ...passed, passed: false, phases: [{ name: "build", ok: false, detail: "near \";\": syntax error" }] };
  renderStep(PublishStep, { data: { ...done, test: { outcome: "failed", result: failed } }, repo: local, last: true });

  await userEvent.click(publish());

  await waitFor(() => expect(git.pullRequestLink).toHaveBeenCalled());
  expect(git.pullRequestLink.mock.calls[0][2]).toContain("## Scratch test\nFailed: build — near \";\": syntax error.\n");
});

it("shows a refused push and lets the developer try again", async () => {
  git.pushRepo.mockRejectedValueOnce(new Error("could not read Username for 'https://github.com'"));
  const { context } = renderStep(PublishStep, { data: done, repo: local, last: true });

  await userEvent.click(publish());

  expect(await screen.findByRole("alert")).toHaveTextContent("could not read Username");
  expect(git.pullRequestLink).not.toHaveBeenCalled();
  expect(context().published).toBe(false);
  await userEvent.click(publish());
  expect(await screen.findByRole("link", { name: "Open the pull request page" })).toBeInTheDocument();
});

it("still gives the text when the link cannot be built", async () => {
  git.pullRequestLink.mockRejectedValue(new Error("Switch to a branch first."));
  renderStep(PublishStep, { data: done, repo: local, last: true });

  await userEvent.click(publish());

  expect(await screen.findByRole("alert")).toHaveTextContent("Switch to a branch first.");
  expect(screen.getByRole("textbox", { name: "Pull request description" })).toHaveValue(BODY);
});

it("cannot publish a detached head", () => {
  renderStep(PublishStep, { data: done, repo: { ...local, detached: true, branch: "" }, last: true });

  expect(publish()).toBeDisabled();
  expect(screen.getByText("Switch to a branch first.")).toBeInTheDocument();
});

it("finishes with Finish, pushed or not", async () => {
  const { onNext } = renderStep(PublishStep, { data: done, repo: local, last: true });

  await userEvent.click(screen.getByRole("button", { name: "Finish" }));

  expect(onNext).toHaveBeenCalledTimes(1);
  expect(git.pushRepo).not.toHaveBeenCalled();
});

it("goes back", async () => {
  const { onBack } = renderStep(PublishStep, { data: done, repo: local, last: true });

  await userEvent.click(screen.getByRole("button", { name: "Back" }));

  expect(onBack).toHaveBeenCalledTimes(1);
});
