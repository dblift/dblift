import { expect, it } from "vitest";

import { describeActivity } from "./activity";

it("describes the events of the status job", () => {
  expect(describeActivity("info.started")).toBe("Reading migration status…");
  expect(describeActivity("info.completed")).toBe("Status read");
});

it("falls back to a neutral text for any other event", () => {
  expect(describeActivity("job.finished")).toBe("Working…");
  expect(describeActivity("something.new")).toBe("Working…");
});
