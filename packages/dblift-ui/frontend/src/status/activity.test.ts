import { expect, it } from "vitest";

import { describeActivity, describeEvent } from "./activity";

it("describes the events of the status job", () => {
  expect(describeActivity("info.started")).toBe("Reading migration status…");
  expect(describeActivity("info.completed")).toBe("Status read");
});

it("falls back to a neutral text for any other event", () => {
  expect(describeActivity("job.finished")).toBe("Working…");
  expect(describeActivity("something.new")).toBe("Working…");
});

it("puts a script's name in the words for its events", () => {
  expect(describeEvent({ event: "migration.script.started", script: "V1_0_2__add_phone.sql" })).toBe(
    "Running V1_0_2__add_phone.sql",
  );
  expect(describeEvent({ event: "migration.script.completed", script: "V1_0_2__add_phone.sql", execution_time: 7 })).toBe(
    "Applied V1_0_2__add_phone.sql in 7 ms",
  );
  expect(describeEvent({ event: "migration.script.failed", script: "V1_0_3__bad.sql", error: "syntax error" })).toBe(
    "Failed V1_0_3__bad.sql: syntax error",
  );
  expect(describeEvent({ event: "undo.script.rolled_back", script: "U1_0_2__add_phone.sql" })).toBe(
    "Reverted with U1_0_2__add_phone.sql",
  );
});

it("has plain words for operation-level events and a fallback", () => {
  expect(describeEvent({ event: "migration.started" })).toBe("Applying migrations…");
  expect(describeEvent({ event: "repair.completed" })).toBe("History repaired");
  expect(describeEvent({ event: "undo.failed", error: "No undo script found" })).toBe("Undo failed: No undo script found");
  expect(describeEvent({ event: "something.else" })).toBe("something.else");
});
