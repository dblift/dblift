import { expect, it } from "vitest";

import { liveStates } from "./live";

it("follows a script from running to applied", () => {
  expect(liveStates([{ event: "migration.script.started", script: "V1_0_0__a.sql" }])).toEqual({
    "V1_0_0__a.sql": "RUNNING",
  });
  expect(
    liveStates([
      { event: "migration.script.started", script: "V1_0_0__a.sql" },
      { event: "migration.script.completed", script: "V1_0_0__a.sql" },
      { event: "migration.script.started", script: "V1_0_1__b.sql" },
    ]),
  ).toEqual({ "V1_0_0__a.sql": "SUCCESS", "V1_0_1__b.sql": "RUNNING" });
});

it("marks a failed script", () => {
  expect(
    liveStates([
      { event: "migration.script.started", script: "V1_0_2__bad.sql" },
      { event: "migration.script.failed", script: "V1_0_2__bad.sql", error: "boom" },
    ]),
  ).toEqual({ "V1_0_2__bad.sql": "FAILED" });
});

it("turns a rolled-back undo script into its migration being pending again", () => {
  expect(liveStates([{ event: "undo.script.rolled_back", script: "U1_0_1__b.sql" }])).toEqual({
    "V1_0_1__b.sql": "PENDING",
  });
});

it("ignores events without a script", () => {
  expect(liveStates([{ event: "migration.started" }, { event: "job.finished" }])).toEqual({});
});

it("ignores the events of an undo script itself; its rollback sets the migration pending", () => {
  expect(
    liveStates([
      { event: "migration.script.started", script: "U1_0_1__b.sql" },
      { event: "migration.script.completed", script: "U1_0_1__b.sql" },
    ]),
  ).toEqual({});
  expect(
    liveStates([
      { event: "migration.script.started", script: "U1_0_1__b.sql" },
      { event: "migration.script.completed", script: "U1_0_1__b.sql" },
      { event: "undo.script.rolled_back", script: "U1_0_1__b.sql" },
    ]),
  ).toEqual({ "V1_0_1__b.sql": "PENDING" });
});

it("leaves the migration untouched when its undo script fails", () => {
  expect(
    liveStates([
      { event: "migration.script.started", script: "U1_0_1__b.sql" },
      { event: "migration.script.failed", script: "U1_0_1__b.sql", error: "boom" },
    ]),
  ).toEqual({});
});
