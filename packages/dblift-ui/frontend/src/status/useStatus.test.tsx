import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { JobEvent, JobResult } from "../api/types";
import { useStatus } from "./useStatus";

const runJob = vi.hoisted(() => vi.fn());
vi.mock("../api/jobs", () => ({ runJob }));

const result: JobResult = { success: true, error: null, current_version: "1.0.0", migrations: [] };

beforeEach(() => {
  runJob.mockReset();
});

it("runs the status job and exposes its result", async () => {
  runJob.mockImplementation(async (_p: string, _c: string, _e: string, onEvent: (e: JobEvent) => void) => {
    onEvent({ event: "info.started" });
    return result;
  });

  const { result: hook } = renderHook(() => useStatus("p1", "staging"));

  expect(hook.current.phase).toBe("loading");
  await waitFor(() => expect(hook.current.phase).toBe("ready"));
  expect(hook.current.result).toEqual(result);
  expect(runJob).toHaveBeenCalledWith("p1", "info", "staging", expect.any(Function));
});

it("reports a failed job as an error", async () => {
  runJob.mockResolvedValue({ ...result, success: false, error: "cannot connect" });

  const { result: hook } = renderHook(() => useStatus("p1", ""));

  await waitFor(() => expect(hook.current.phase).toBe("error"));
  expect(hook.current.error).toBe("cannot connect");
});

it("reports a rejected request as an error", async () => {
  runJob.mockRejectedValue(new Error("invalid token"));

  const { result: hook } = renderHook(() => useStatus("p1", ""));

  await waitFor(() => expect(hook.current.phase).toBe("error"));
  expect(hook.current.error).toBe("invalid token");
});

it("runs again on refresh and when the environment changes", async () => {
  runJob.mockResolvedValue(result);
  const { result: hook, rerender } = renderHook(({ env }) => useStatus("p1", env), {
    initialProps: { env: "" },
  });
  await waitFor(() => expect(hook.current.phase).toBe("ready"));

  act(() => hook.current.refresh());
  await waitFor(() => expect(runJob).toHaveBeenCalledTimes(2));

  rerender({ env: "staging" });
  await waitFor(() => expect(runJob).toHaveBeenCalledTimes(3));
  expect(runJob.mock.calls[2][2]).toBe("staging");
});

it("ignores the answer of a run that was superseded", async () => {
  let finishFirst: (value: JobResult) => void = () => {};
  runJob
    .mockImplementationOnce(() => new Promise<JobResult>((resolve) => (finishFirst = resolve)))
    .mockResolvedValueOnce({ ...result, current_version: "2.0.0" });
  const { result: hook, rerender } = renderHook(({ env }) => useStatus("p1", env), {
    initialProps: { env: "" },
  });

  rerender({ env: "staging" });
  await waitFor(() => expect(hook.current.result?.current_version).toBe("2.0.0"));
  await act(async () => finishFirst({ ...result, current_version: "1.0.0" }));

  expect(hook.current.result?.current_version).toBe("2.0.0");
});
