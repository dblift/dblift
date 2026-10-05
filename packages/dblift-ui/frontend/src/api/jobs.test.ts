import { expect, it } from "vitest";

import { SseParser } from "./jobs";

it("parses complete events", () => {
  const parser = new SseParser();

  const events = parser.push('data: {"event":"info.started"}\n\ndata: {"event":"info.completed"}\n\n');

  expect(events.map((e) => e.event)).toEqual(["info.started", "info.completed"]);
});

it("waits for the rest of an event split across chunks", () => {
  const parser = new SseParser();

  expect(parser.push('data: {"event":"info.st')).toEqual([]);
  expect(parser.push('arted"}\n')).toEqual([]);
  expect(parser.push("\n").map((e) => e.event)).toEqual(["info.started"]);
});

it("ignores lines that are not data", () => {
  const parser = new SseParser();

  expect(parser.push(': keep-alive\n\ndata: {"event":"job.finished"}\n\n').map((e) => e.event)).toEqual([
    "job.finished",
  ]);
});
