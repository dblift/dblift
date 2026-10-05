import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { JobEvent, JobResult } from "../api/types";
import { useCommand } from "./useCommand";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob }));

const ok: JobResult = {
  success: true, error: null, current_version: "1.0.1", migrations: [], sql: [], repaired: null, baseline_version: null,
};

beforeEach(() => {
  runJob.mockReset();
});

it("collects the events of a run and reports its result", async () => {
  runJob.mockImplementation(async (_p: string, _c: string, _e: string, onEvent: (e: JobEvent) => void) => {
    onEvent({ event: "migration.started" });
    onEvent({ event: "migration.script.completed", script: "V1_0_0__a.sql" });
    return ok;
  });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "staging", onChanged));

  let returned: JobResult | null = null;
  await act(async () => {
    returned = await result.current.start("migrate");
  });

  expect(returned).toEqual(ok);
  expect(runJob).toHaveBeenCalledWith("p1", "migrate", "staging", expect.any(Function), {});
  expect(result.current.run).toMatchObject({ command: "migrate", phase: "done", error: null });
  expect(result.current.run?.events.map((e) => e.event)).toEqual(["migration.started", "migration.script.completed"]);
  expect(result.current.busy).toBe(false);
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("is busy while a command runs", async () => {
  let finish: (value: JobResult) => void = () => {};
  runJob.mockImplementation(() => new Promise<JobResult>((resolve) => (finish = resolve)));
  const { result } = renderHook(() => useCommand("p1", "", () => {}));

  act(() => {
    void result.current.start("migrate");
  });
  await waitFor(() => expect(result.current.busy).toBe(true));
  expect(result.current.run?.phase).toBe("running");

  await act(async () => finish(ok));
  expect(result.current.busy).toBe(false);
});

it("reports a command that finished unsuccessfully", async () => {
  runJob.mockResolvedValue({ ...ok, success: false, error: "Failed to execute statement 2" });
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  await act(async () => {
    await result.current.start("migrate");
  });

  expect(result.current.run).toMatchObject({ phase: "failed", error: "Failed to execute statement 2" });
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("reports a refused command without calling onChanged", async () => {
  runJob.mockRejectedValue(new ApiError(409, "Another change is running on this project. Wait for it to finish."));
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  let returned: JobResult | null = ok;
  await act(async () => {
    returned = await result.current.start("migrate");
  });

  expect(returned).toBeNull();
  expect(result.current.run).toMatchObject({ phase: "failed", error: expect.stringContaining("Another change") });
  expect(onChanged).not.toHaveBeenCalled();
});

it("does not call onChanged for commands that change nothing", async () => {
  runJob.mockResolvedValue(ok);
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  await act(async () => {
    await result.current.start("preview");
    await result.current.start("validate");
  });

  expect(onChanged).not.toHaveBeenCalled();
});

it("passes parameters and can be dismissed", async () => {
  runJob.mockResolvedValue(ok);
  const { result } = renderHook(() => useCommand("p1", "", () => {}));

  await act(async () => {
    await result.current.start("baseline", { version: "1.0.0" });
  });
  expect(runJob.mock.calls[0][4]).toEqual({ version: "1.0.0" });

  act(() => result.current.dismiss());
  expect(result.current.run).toBeNull();
});

it("re-reads the status when a change's stream breaks after the job started", async () => {
  runJob.mockRejectedValue(new ApiError(0, "job stream ended before the job finished"));
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  await act(async () => {
    await result.current.start("migrate");
  });

  expect(result.current.run).toMatchObject({ phase: "failed", error: "job stream ended before the job finished" });
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("re-reads the status when a change fails for an unknown reason", async () => {
  runJob.mockRejectedValue(new Error("network down"));
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  await act(async () => {
    await result.current.start("migrate");
  });

  expect(result.current.run).toMatchObject({ phase: "failed", error: "network down" });
  expect(onChanged).toHaveBeenCalledTimes(1);
});

it("does not re-read the status when a command that changes nothing fails", async () => {
  runJob.mockRejectedValue(new ApiError(0, "job stream ended before the job finished"));
  const onChanged = vi.fn();
  const { result } = renderHook(() => useCommand("p1", "", onChanged));

  await act(async () => {
    await result.current.start("validate");
  });

  expect(result.current.run?.phase).toBe("failed");
  expect(onChanged).not.toHaveBeenCalled();
});
