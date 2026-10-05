import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/client";
import type { JobEvent, JobResult, ScratchPhase, ScratchPlan, ScratchResult } from "../../api/types";
import { renderStep, U, V } from "../../test/wizard";
import TestStep from "./TestStep";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../../api/jobs", () => ({ runJob, readJobLog: vi.fn() }));
const scratch = vi.hoisted(() => ({ getScratchPlan: vi.fn() }));
vi.mock("../../api/scratch", () => scratch);
const git = vi.hoisted(() => ({ getRepo: vi.fn() }));
vi.mock("../../api/git", () => git);

// What the server sends for the strategies that start no container.
const NO_CONTAINER = { runtime: "", image: "", image_present: null, image_size_mb: null };
const FILE: ScratchPlan = {
  strategy: "file", engine: "sqlite",
  summary: "A temporary SQLite database is created, used and deleted. Your databases are not touched.", warning: "", ...NO_CONTAINER,
};
const ENVIRONMENT: ScratchPlan = {
  strategy: "environment", engine: "postgresql",
  summary: "The environment named scratch is emptied, then used for the test.",
  warning: "Everything in the scratch environment's database is deleted first.", ...NO_CONTAINER,
};
const SKIP: ScratchPlan = {
  strategy: "skip", engine: "postgresql",
  summary: "No scratch database is available for this engine yet. Add an environment named scratch to the config, or continue without the test.",
  warning: "", ...NO_CONTAINER,
};
const PRESENT: ScratchPlan = {
  strategy: "container", engine: "postgresql",
  summary: "A throwaway PostgreSQL database is started in a container (Apple container, image postgres:16), used for the test and removed. Your databases are not touched.",
  warning: "", runtime: "Apple container", image: "postgres:16", image_present: true, image_size_mb: 160,
};
const ABSENT: ScratchPlan = { ...PRESENT, image_present: false };
const ABSENT_NOTICE = "The image postgres:16 is not on this machine (about 160 MB).";

const BUILT = "3 migrations applied from an empty database.";
const NO_TABLE = "Failed to execute statement 1 in U1_0_2__add_invoices.sql: no such table: invoice\nDROP TABLE invoice;";
const phase = (name: ScratchPhase["name"], ok: boolean | null, detail: string): ScratchPhase => ({ name, ok, detail });
const allPassed: ScratchPhase[] = [
  phase("build", true, BUILT), phase("undo", true, `${U} reverted ${V}.`), phase("reapply", true, `${V} applied again after its undo.`),
];
const undoFailed: ScratchPhase[] = [phase("build", true, BUILT), phase("undo", false, NO_TABLE), phase("reapply", null, "Not run.")];

function finished(phases: ScratchPhase[], extra: Partial<ScratchResult> = {}): JobResult {
  const passed = phases.every((p) => p.ok !== false);
  return {
    success: passed, error: passed ? null : "undo: Failed to execute statement 1", current_version: null, migrations: [], sql: [], repaired: null,
    baseline_version: null, job_id: "j1", has_log: true, message: null,
    scratch: { strategy: "file", passed, skipped: false, phases, script: V, ...extra },
  };
}
/** The events the server publishes for these phases, as the job runs. */
function eventsOf(phases: ScratchPhase[]): JobEvent[] {
  return phases.flatMap((p) => {
    const end: JobEvent = { event: "scratch.phase", phase: p.name, status: p.ok === null ? "skipped" : p.ok ? "passed" : "failed", detail: p.detail };
    return p.detail === "Not run." ? [end] : [{ event: "scratch.phase", phase: p.name, status: "started", detail: "" }, end];
  });
}
function answers(phases: ScratchPhase[], extra: Partial<ScratchResult> = {}) {
  runJob.mockImplementationOnce(async (_p: string, _c: string, _e: string, onEvent: (event: JobEvent) => void) => {
    eventsOf(phases).forEach(onEvent);
    return finished(phases, extra);
  });
}
/** A run the test drives by hand: it sends events, then finishes. */
function controlled() {
  const run: { send: (event: JobEvent) => void; finish: (result: JobResult) => void } = { send: () => {}, finish: () => {} };
  runJob.mockImplementationOnce(
    (_p: string, _c: string, _e: string, onEvent: (event: JobEvent) => void) =>
      new Promise<JobResult>((resolve) => {
        run.send = (event) => act(() => onEvent(event));
        run.finish = (result) => act(() => resolve(result));
      }),
  );
  return run;
}

beforeEach(() => {
  runJob.mockReset();
  scratch.getScratchPlan.mockReset();
  scratch.getScratchPlan.mockResolvedValue(FILE);
  git.getRepo.mockResolvedValue({ repository: false });
});

const written = { scripts: { migration: V, undo: U }, description: "Add invoices", written: true };
const runTest = () => screen.getByRole("button", { name: "Run the test" });
const phases = () => screen.getByRole("list", { name: "Test phases" });
const item = (label: string) => within(phases()).getByText(label).closest("li")!;

it("shows how the test will run before anything runs", async () => {
  scratch.getScratchPlan.mockResolvedValue(ENVIRONMENT);
  renderStep(TestStep, { data: written });

  expect(await screen.findByText(ENVIRONMENT.summary)).toBeInTheDocument();
  expect(screen.getByText(ENVIRONMENT.warning)).toBeInTheDocument();
  expect(scratch.getScratchPlan).toHaveBeenCalledWith("p1");
  expect(runJob).not.toHaveBeenCalled();
});

it("runs the scratch test on the new migration", async () => {
  answers(allPassed);
  renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  expect(runJob).toHaveBeenCalledWith("p1", "scratch_test", "", expect.any(Function), { script: V });
});

it("shows each phase as it is reported, with its state in words", async () => {
  const run = controlled();
  renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  run.send({ event: "scratch.phase", phase: "build", status: "started", detail: "" });
  expect(item("Build from zero")).toHaveTextContent("running");
  expect(within(phases()).getAllByRole("listitem")).toHaveLength(1);

  run.send({ event: "scratch.phase", phase: "build", status: "passed", detail: BUILT });
  run.send({ event: "migration.started", script: V });
  run.send({ event: "scratch.phase", phase: "undo", status: "started", detail: "" });
  expect(item("Build from zero")).toHaveTextContent("passed");
  expect(item("Build from zero")).toHaveTextContent(BUILT);
  expect(item("Undo the new migration")).toHaveTextContent("running");

  run.send({ event: "scratch.phase", phase: "undo", status: "skipped", detail: "This migration has no undo script." });
  run.send({ event: "scratch.phase", phase: "reapply", status: "started", detail: "" });
  run.send({ event: "scratch.phase", phase: "reapply", status: "skipped", detail: "Nothing was undone, so nothing is applied again." });
  expect(item("Undo the new migration")).toHaveTextContent("skipped");
  expect(item("Apply it again")).toHaveTextContent("skipped");
  expect(within(phases()).getAllByRole("listitem")).toHaveLength(3);
});

it("cannot run twice at once nor continue while the test runs", async () => {
  const run = controlled();
  renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  expect(runTest()).toBeDisabled();
  expect(screen.getByRole("button", { name: "Continue without the test" })).toBeDisabled();
  run.finish(finished(allPassed));
  expect(await screen.findByRole("button", { name: "Run again" })).toBeEnabled();
});

it("keeps the wizard open while the test runs, whatever its end", async () => {
  const run = controlled();
  const { context } = renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  expect(context().busy).toBe("The test is running…");
  run.finish(finished(undoFailed));
  await screen.findByRole("button", { name: "Run again" });
  expect(context().busy).toBeNull();

  runJob.mockRejectedValueOnce(new Error("stream lost"));
  await userEvent.click(screen.getByRole("button", { name: "Run again" }));
  expect(await screen.findByText("stream lost")).toBeInTheDocument();
  expect(context().busy).toBeNull();
});

it("enables Next once the test passed, and records the outcome", async () => {
  answers(allPassed);
  const { context, onNext } = renderStep(TestStep, { data: written });
  await screen.findByText(FILE.summary);
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

  await userEvent.click(runTest());

  expect(await screen.findByText("The test passed.")).toBeInTheDocument();
  ["Build from zero", "Undo the new migration", "Apply it again"].forEach((label) => expect(item(label)).toHaveTextContent("passed"));
  expect(context().test).toEqual({ outcome: "passed", result: finished(allPassed).scratch });
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(onNext).toHaveBeenCalledTimes(1);
});

it("shows the database's error of the failing phase in an alert, with the way back and Run again", async () => {
  answers(undoFailed);
  const { context, onBack } = renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Undo the new migration failed.");
  const pre = alert.querySelector("pre")!;
  expect(pre.textContent).toBe(NO_TABLE);
  expect(item("Undo the new migration")).toHaveTextContent("failed");
  expect(item("Apply it again")).toHaveTextContent("skipped");
  expect(context().test.outcome).toBe("failed");
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

  await userEvent.click(screen.getByRole("button", { name: "Back to the scripts" }));
  expect(onBack).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
});

it("starts afresh when run again: the earlier phases go", async () => {
  answers(undoFailed);
  renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
  await screen.findByRole("alert");

  const run = controlled();
  await userEvent.click(screen.getByRole("button", { name: "Run again" }));

  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Test phases" })).not.toBeInTheDocument();
  run.send({ event: "scratch.phase", phase: "build", status: "started", detail: "" });
  expect(within(phases()).getAllByRole("listitem")).toHaveLength(1);
  run.finish(finished(allPassed));
  expect(await screen.findByText("The test passed.")).toBeInTheDocument();
});

it("can always go on without the test, which is then marked skipped", async () => {
  const { context, onNext } = renderStep(TestStep, { data: written });

  await userEvent.click(screen.getByRole("button", { name: "Continue without the test" }));

  expect(context().test.outcome).toBe("skipped");
  expect(onNext).toHaveBeenCalledTimes(1);
  expect(runJob).not.toHaveBeenCalled();
});

it("keeps a failed outcome when the developer goes on without the test after a failure", async () => {
  answers(undoFailed);
  const { context, onNext } = renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
  await screen.findByRole("alert");

  expect(context().test.continued).toBeUndefined();
  await userEvent.click(screen.getByRole("button", { name: "Continue without the test" }));

  expect(context().test.outcome).toBe("failed");
  expect(context().test.continued).toBe(true);
  expect(onNext).toHaveBeenCalledTimes(1);
});

it("offers no way to skip a test that passed, until the scripts change", async () => {
  answers(allPassed);
  const { context } = renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
  await screen.findByText("The test passed.");

  expect(screen.queryByRole("button", { name: "Continue without the test" })).not.toBeInTheDocument();
  act(() => context().update({ test: { outcome: null, result: context().test.result } }));
  expect(screen.getByRole("button", { name: "Continue without the test" })).toBeEnabled();
});

it("offers only the explanation and Continue without the test when no scratch database exists", async () => {
  scratch.getScratchPlan.mockResolvedValue(SKIP);
  renderStep(TestStep, { data: written });

  expect(await screen.findByText(SKIP.summary)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Run the test" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue without the test" })).toBeEnabled();
});

it("asks before emptying the scratch environment the first time, and only then", async () => {
  scratch.getScratchPlan.mockResolvedValue(ENVIRONMENT);
  answers(allPassed);
  answers(allPassed);
  renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
  expect(screen.getByText("Empty the scratch environment and run the test?")).toBeInTheDocument();
  expect(runJob).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(runJob).not.toHaveBeenCalled();
  expect(runTest()).toHaveFocus();

  await userEvent.click(runTest());
  await userEvent.click(screen.getByRole("button", { name: "Empty and run" }));
  await screen.findByText("The test passed.");
  expect(runJob).toHaveBeenCalledTimes(1);

  await userEvent.click(screen.getByRole("button", { name: "Run again" }));
  await waitFor(() => expect(runJob).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("Empty the scratch environment and run the test?")).not.toBeInTheDocument();
});

it("cancels the question with Escape, without closing the wizard", async () => {
  scratch.getScratchPlan.mockResolvedValue(ENVIRONMENT);
  const keys: string[] = [];
  const listen = (event: KeyboardEvent) => keys.push(event.key);
  window.addEventListener("keydown", listen);
  renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  fireEvent.keyDown(screen.getByRole("button", { name: "Cancel" }), { key: "Escape" });

  window.removeEventListener("keydown", listen);
  expect(screen.queryByText("Empty the scratch environment and run the test?")).not.toBeInTheDocument();
  expect(keys).toEqual([]);
});

it("shows a refused start as a message and stays usable", async () => {
  runJob.mockRejectedValueOnce(new ApiError(409, "Another change is running on this project. Wait for it to finish."));
  answers(allPassed);
  const { context } = renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Another change is running on this project. Wait for it to finish.");
  expect(context().test.outcome).toBeNull();
  expect(runTest()).toBeEnabled();
  await userEvent.click(runTest());
  expect(await screen.findByText("The test passed.")).toBeInTheDocument();
});

it("shows the job's own error when the test could not run at all", async () => {
  runJob.mockResolvedValueOnce({ ...finished([]), success: false, error: "no script named V1_0_2__add_invoices.sql", scratch: null });
  const { context } = renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  const alert = await screen.findByRole("alert");
  expect(alert.querySelector("pre")!.textContent).toBe("no script named V1_0_2__add_invoices.sql");
  expect(context().test).toEqual({ outcome: "failed", result: null });
  expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
});

it("records a test the server skipped as skipped", async () => {
  runJob.mockResolvedValueOnce({ ...finished([]), scratch: { strategy: "skip", passed: false, skipped: true, phases: [], script: V } });
  const { context } = renderStep(TestStep, { data: written });

  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

  expect(await screen.findByText("No scratch database was available: the test was skipped.")).toBeInTheDocument();
  expect(context().test.outcome).toBe("skipped");
});

it("asks for a new run once the scripts changed after a run", async () => {
  answers(allPassed);
  const { context } = renderStep(TestStep, { data: written });
  await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
  await screen.findByText("The test passed.");

  act(() => context().update({ test: { outcome: null, result: context().test.result } }));

  expect(screen.getByText("The scripts changed since this run. Run the test again.")).toBeInTheDocument();
  expect(screen.queryByText("The test passed.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
});

it("says when the plan cannot be read, and still lets the developer go on", async () => {
  scratch.getScratchPlan.mockRejectedValue(new Error("unknown project"));
  renderStep(TestStep, { data: written });

  expect(await screen.findByRole("alert")).toHaveTextContent("unknown project");
  expect(screen.queryByRole("button", { name: "Run the test" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Continue without the test" })).toBeEnabled();
});

it("goes back", async () => {
  const { onBack } = renderStep(TestStep, { data: written });

  await userEvent.click(screen.getByRole("button", { name: "Back" }));

  expect(onBack).toHaveBeenCalledTimes(1);
});

describe("with a container", () => {
  const startPassed = phase("start", true, "Ready in 2 s.");

  it("shows the summary, the runtime and the image before anything runs", async () => {
    scratch.getScratchPlan.mockResolvedValue(PRESENT);
    renderStep(TestStep, { data: written });

    expect(await screen.findByText(PRESENT.summary)).toBeInTheDocument();
    const facts = screen.getByRole("list", { name: "What the test starts" });
    expect(within(facts).getByText("Apple container")).toBeInTheDocument();
    expect(within(facts).getByText("postgres:16")).toBeInTheDocument();
    expect(runJob).not.toHaveBeenCalled();
  });

  it("runs the test without downloading anything when the image is on this machine", async () => {
    scratch.getScratchPlan.mockResolvedValue(PRESENT);
    answers([startPassed, ...allPassed]);
    renderStep(TestStep, { data: written });

    await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

    expect(await screen.findByText("The test passed.")).toBeInTheDocument();
    expect(runJob).toHaveBeenCalledWith("p1", "scratch_test", "", expect.any(Function), { script: V });
    expect(screen.queryByText(ABSENT_NOTICE)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download and run" })).not.toBeInTheDocument();
  });

  it("says when the image is not on this machine, and downloads it only from Download and run", async () => {
    scratch.getScratchPlan.mockResolvedValue(ABSENT);
    answers([startPassed, ...allPassed]);
    renderStep(TestStep, { data: written });

    expect(await screen.findByText(ABSENT_NOTICE)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run the test" })).not.toBeInTheDocument();
    expect(runJob).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Download and run" }));

    expect(runJob).toHaveBeenCalledWith("p1", "scratch_test", "", expect.any(Function), { script: V, pull: true });
  });

  it("says in the start phase that the image is downloading, and keeps the wizard open meanwhile", async () => {
    scratch.getScratchPlan.mockResolvedValue(ABSENT);
    const run = controlled();
    const { context } = renderStep(TestStep, { data: written });
    await userEvent.click(await screen.findByRole("button", { name: "Download and run" }));

    run.send({ event: "scratch.phase", phase: "start", status: "started", detail: "Downloading postgres:16…" });

    expect(item("Start the scratch database")).toHaveTextContent("running");
    expect(item("Start the scratch database")).toHaveTextContent("Downloading postgres:16…");
    expect(context().busy).toBe("The test is running…");
    expect(screen.getByRole("button", { name: "Continue without the test" })).toBeDisabled();
    run.finish(finished([startPassed, ...allPassed]));
    expect(await screen.findByText("The test passed.")).toBeInTheDocument();
    expect(context().busy).toBeNull();
  });

  it("reads the plan again after a run: Run again does not download an image that is now here", async () => {
    scratch.getScratchPlan.mockResolvedValueOnce(ABSENT).mockResolvedValue(PRESENT);
    answers([startPassed, ...undoFailed]);
    answers([startPassed, ...allPassed]);
    renderStep(TestStep, { data: written });
    await userEvent.click(await screen.findByRole("button", { name: "Download and run" }));
    await screen.findByText("Undo the new migration failed.");

    await waitFor(() => expect(screen.queryByText(ABSENT_NOTICE)).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Run again" }));

    await screen.findByText("The test passed.");
    expect(runJob).toHaveBeenLastCalledWith("p1", "scratch_test", "", expect.any(Function), { script: V });
    await waitFor(() => expect(scratch.getScratchPlan).toHaveBeenCalledTimes(3));
  });

  it("offers Download and run again when the image is still missing after a failed run", async () => {
    const missing = "The image postgres:16 is not on this machine.";
    scratch.getScratchPlan.mockResolvedValueOnce(PRESENT).mockResolvedValue(ABSENT);
    answers([phase("start", false, missing), phase("build", null, "Not run."), phase("undo", null, "Not run."), phase("reapply", null, "Not run.")]);
    renderStep(TestStep, { data: written });
    await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));
    expect(await screen.findByText("Start the scratch database failed.")).toBeInTheDocument();

    expect(await screen.findByText(ABSENT_NOTICE)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run again" })).not.toBeInTheDocument();
    answers([startPassed, ...allPassed]);
    await userEvent.click(screen.getByRole("button", { name: "Download and run" }));

    expect(runJob).toHaveBeenLastCalledWith("p1", "scratch_test", "", expect.any(Function), { script: V, pull: true });
  });

  it("warns under the phases when the container could not be removed", async () => {
    const cleanup = "The container dblift-ui-1-2 could not be removed. Remove it with Apple container.";
    const warning = `The scratch container could not be removed: ${cleanup}`;
    scratch.getScratchPlan.mockResolvedValue(PRESENT);
    answers([startPassed, ...allPassed], { cleanup });
    renderStep(TestStep, { data: written });

    await userEvent.click(await screen.findByRole("button", { name: "Run the test" }));

    expect(await screen.findByText(warning)).toBeInTheDocument();
    expect(phases().compareDocumentPosition(screen.getByText(warning)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the server's reason when no container can be used, as it is", async () => {
    const reason = "No container runtime was found (Docker, Podman or Apple container).";
    scratch.getScratchPlan.mockResolvedValue({ ...SKIP, summary: reason });
    renderStep(TestStep, { data: written });

    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run the test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download and run" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue without the test" })).toBeEnabled();
  });
});
