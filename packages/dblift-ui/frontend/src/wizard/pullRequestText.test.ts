import { expect, it } from "vitest";

import type { ScratchPhase, ScratchResult } from "../api/types";
import { onMain, project, U, V } from "../test/wizard";
import { pullRequestText } from "./pullRequestText";
import { START, type WizardContext } from "./steps";

function context(over: Partial<WizardContext> = {}): WizardContext {
  return {
    ...START, project, repo: onMain, update: () => {}, changed: () => {},
    description: "Add invoices", scripts: { migration: V, undo: U }, ...over,
  };
}
const ok = (name: ScratchPhase["name"]): ScratchPhase => ({ name, ok: true, detail: "" });
function result(strategy: string, phases: ScratchPhase[]): ScratchResult {
  const passed = phases.every((p) => p.ok !== false);
  return { strategy, passed, skipped: false, phases, script: V };
}
const passedOn = (strategy: string) => ({ outcome: "passed" as const, result: result(strategy, [ok("build"), ok("undo"), ok("reapply")]) });

const body = (test: string, undo = `- ${U}`, change = "Add invoices") =>
  `## Change\n${change}\n\n## Scripts\n- ${V}\n${undo}\n\n## Scratch test\n${test}\n`;

it("titles the pull request with the description's first line", () => {
  expect(pullRequestText(context({ description: "Add invoices\n\nWith their lines.", test: passedOn("file") })).title).toBe("Add invoices");
});

it("keeps the title to 72 characters", () => {
  const long = "Add the invoices table, its lines, the payments of each invoice and the refunds made afterwards";
  const { title } = pullRequestText(context({ description: long, test: passedOn("file") }));

  expect(title).toHaveLength(72);
  expect(title).toBe(`${long.slice(0, 71).trimEnd()}…`);
});

it("describes a test passed on a temporary SQLite database", () => {
  const { body: text } = pullRequestText(context({ test: passedOn("file") }));

  expect(text).toBe(body("Passed on a temporary SQLite database: build from zero, undo, re-apply."));
});

it("describes a test passed on the scratch environment", () => {
  const phases = [ok("clean"), ok("build"), ok("undo"), ok("reapply")];
  const { body: text } = pullRequestText(context({ test: { outcome: "passed", result: result("environment", phases) } }));

  expect(text).toBe(body("Passed on the scratch environment: build from zero, undo, re-apply."));
});

it("describes a test passed on a throwaway database in a container", () => {
  const phases = [ok("start"), ok("build"), ok("undo"), ok("reapply")];
  const { body: text } = pullRequestText(context({ test: { outcome: "passed", result: result("container", phases) } }));

  expect(text).toBe(body("Passed on a throwaway database in a container: build from zero, undo, re-apply."));
});

it("says undo and re-apply were not run when there is no undo script", () => {
  const phases: ScratchPhase[] = [
    ok("build"),
    { name: "undo", ok: null, detail: "This migration has no undo script." },
    { name: "reapply", ok: null, detail: "Nothing was undone, so nothing is applied again." },
  ];
  const { body: text } = pullRequestText(
    context({ scripts: { migration: V, undo: null }, test: { outcome: "passed", result: result("file", phases) } }),
  );

  expect(text).toBe(body("Passed (no undo script: undo and re-apply were not run).", "- no undo script"));
});

it("says a skipped test leaves the check to CI", () => {
  const { body: text } = pullRequestText(context({ test: { outcome: "skipped", result: null } }));

  expect(text).toBe(body("Skipped. CI should run the migrations before this is merged."));
});

it("never describes a failed test as passed: it names the phase and the first line of the error", () => {
  const phases: ScratchPhase[] = [
    ok("build"),
    { name: "undo", ok: false, detail: "Failed to execute statement 1 in U1_0_2__add_invoices.sql: no such table: invoice\nDROP TABLE invoice;" },
    { name: "reapply", ok: null, detail: "Not run." },
  ];
  const { body: text } = pullRequestText(context({ test: { outcome: "failed", result: result("file", phases) } }));

  expect(text).toBe(body("Failed: undo — Failed to execute statement 1 in U1_0_2__add_invoices.sql: no such table: invoice."));
  expect(text).not.toContain("Passed");
});

it("ends a failure with one full stop when the error already has one", () => {
  const phases: ScratchPhase[] = [
    { name: "clean", ok: false, detail: "The scratch environment points at the same database as default. Nothing was done." },
  ];
  const { body: text } = pullRequestText(context({ test: { outcome: "failed", result: result("environment", phases) } }));

  expect(text).toContain("Failed: clean — The scratch environment points at the same database as default. Nothing was done.\n");
});

it("says a test that could not run failed", () => {
  const { body: text } = pullRequestText(context({ test: { outcome: "failed", result: null } }));

  expect(text).toBe(body("Failed: the test could not run."));
});

it("keeps a failed outcome failed even when the last result had passed", () => {
  const { body: text } = pullRequestText(context({ test: { outcome: "failed", result: passedOn("file").result } }));

  expect(text).toContain("## Scratch test\nFailed");
  expect(text).not.toContain("Passed");
});

it("puts the whole description under Change", () => {
  const { body: text } = pullRequestText(context({ description: "  Add invoices\n\nWith their lines.  ", test: passedOn("file") }));

  expect(text.startsWith("## Change\nAdd invoices\n\nWith their lines.\n\n## Scripts\n")).toBe(true);
});
