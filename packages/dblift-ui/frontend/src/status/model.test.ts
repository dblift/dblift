import { expect, it } from "vitest";

import type { Migration } from "../api/types";
import { isApplied, latestPerScript, railFill, stateInfo, summarize, undoNameOf, versionLabel } from "./model";

function migration(script: string, status: string, overrides: Partial<Migration> = {}): Migration {
  return {
    script,
    version: script.slice(1).split("__")[0].replaceAll("_", "."),
    description: script.split("__")[1].replace(".sql", ""),
    type: "SQL",
    status,
    installed_on: "",
    installed_by: "",
    execution_time: 0,
    ...overrides,
  };
}

it("keeps the latest entry of a script that appears several times", () => {
  const history = [
    migration("V1_0_0__a.sql", "SUCCESS"),
    migration("V1_0_1__b.sql", "UNDONE"),
    migration("V1_0_1__b.sql", "PENDING"),
  ];

  const merged = latestPerScript(history);

  expect(merged.map((m) => [m.script, m.status])).toEqual([
    ["V1_0_0__a.sql", "SUCCESS"],
    ["V1_0_1__b.sql", "PENDING"],
  ]);
});

it("counts applied, pending and failed", () => {
  const list = [
    migration("V1_0_0__a.sql", "SUCCESS"),
    migration("V1_0_1__b.sql", "SUCCESS"),
    migration("V1_0_2__c.sql", "FAILED"),
    migration("V1_0_3__d.sql", "PENDING"),
  ];

  expect(summarize(list)).toEqual({ applied: 2, pending: 1, failed: 1 });
});

it("fills the rail up to the middle of the last applied node", () => {
  const list = [
    migration("V1_0_0__a.sql", "SUCCESS"),
    migration("V1_0_1__b.sql", "SUCCESS"),
    migration("V1_0_2__c.sql", "PENDING"),
    migration("V1_0_3__d.sql", "PENDING"),
  ];

  expect(railFill(list)).toBeCloseTo(1.5 / 4);
  expect(railFill([])).toBe(0);
  expect(railFill(list.map((m) => ({ ...m, status: "PENDING" })))).toBe(0);
});

it("describes the states the engine reports, including the ones with spaces", () => {
  expect(stateInfo("SUCCESS")).toMatchObject({ label: "Applied", tone: "ok", applied: true });
  expect(stateInfo("PENDING")).toMatchObject({ label: "Pending", tone: "warn", applied: false });
  expect(stateInfo("FAILED")).toMatchObject({ label: "Failed", tone: "error", applied: false });
  expect(stateInfo("UNDONE")).toMatchObject({ label: "Undone", tone: "muted", applied: false });
  expect(stateInfo("OUT OF ORDER")).toMatchObject({ label: "Out of order", tone: "warn", applied: true });
  expect(stateInfo("MISSING")).toMatchObject({ label: "Missing", tone: "error", applied: true });
  expect(stateInfo("BASELINE")).toMatchObject({ label: "Baseline", tone: "info", applied: true });
  expect(stateInfo("BELOW BASELINE")).toMatchObject({ label: "Below baseline", tone: "muted", applied: false });
  expect(stateInfo("RUNNING")).toMatchObject({ label: "Running", tone: "info", applied: false });
  expect(stateInfo("something new")).toMatchObject({ label: "something new", tone: "info", applied: false });
  expect(stateInfo("SUCCESS").hint).not.toBe("");
});

it("counts out-of-order and missing migrations as applied", () => {
  const list = [
    migration("V1_0_0__a.sql", "SUCCESS"),
    migration("V1_0_2__c.sql", "MISSING"),
    migration("V1_0_1__b.sql", "OUT OF ORDER"),
    migration("V1_0_3__d.sql", "PENDING"),
  ];

  expect(summarize(list)).toEqual({ applied: 3, pending: 1, failed: 0 });
  expect(railFill(list)).toBeCloseTo(2.5 / 4);
  expect(isApplied("OUT OF ORDER")).toBe(true);
  expect(isApplied("BELOW BASELINE")).toBe(false);
});

it("knows the outdated state of a repeatable script", () => {
  expect(stateInfo("OUTDATED")).toMatchObject({ label: "Outdated", tone: "warn", applied: true });
});

it("names the undo script of a migration", () => {
  expect(undoNameOf("V1_0_2__add_phone.sql")).toBe("U1_0_2__add_phone.sql");
  expect(undoNameOf("V3__seed.py")).toBe("U3__seed.py");
});

it("labels a script without version as repeatable", () => {
  expect(versionLabel({ version: "1.0.2" })).toBe("1.0.2");
  expect(versionLabel({ version: "" })).toBe("repeatable");
});
