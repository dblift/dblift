import { firstLine } from "./slug";
import type { WizardContext } from "./steps";

const MAX_TITLE = 72;

/** What the scratch test proved, in one sentence; a failed test is never described as passed. */
function testLine({ test, scripts }: WizardContext): string {
  const { outcome, result } = test;
  if (outcome === "failed") {
    const failing = result?.phases.find((p) => p.ok === false);
    if (!failing) {
      return "Failed: the test could not run.";
    }
    const reason = failing.detail.trim().split("\n")[0].trim().replace(/\.+$/, "");
    return `Failed: ${failing.name} — ${reason}.`;
  }
  if (outcome === "passed") {
    const undone = scripts?.undo && !result?.phases.some((p) => p.name === "undo" && p.ok === null);
    if (!undone) {
      return "Passed (no undo script: undo and re-apply were not run).";
    }
    return result?.strategy === "environment"
      ? "Passed on the scratch environment: build from zero, undo, re-apply."
      : "Passed on a temporary SQLite database: build from zero, undo, re-apply.";
  }
  return "Skipped. CI should run the migrations before this is merged.";
}

/** The pull request's title and description for the change the wizard made. */
export function pullRequestText(context: WizardContext): { title: string; body: string } {
  const line = firstLine(context.description);
  const title = line.length > MAX_TITLE ? `${line.slice(0, MAX_TITLE - 1).trimEnd()}…` : line;
  const scripts = context.scripts;
  const body = [
    "## Change",
    context.description.trim(),
    "",
    "## Scripts",
    `- ${scripts?.migration ?? ""}`,
    scripts?.undo ? `- ${scripts.undo}` : "- no undo script",
    "",
    "## Scratch test",
    testLine(context),
    "",
  ].join("\n");
  return { title, body };
}
