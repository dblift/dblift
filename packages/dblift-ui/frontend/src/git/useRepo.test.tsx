import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { RepoStatus } from "../api/types";
import { useRepo } from "./useRepo";

const api = vi.hoisted(() => ({ getRepo: vi.fn() }));
vi.mock("../api/git", () => api);

const main: RepoStatus = {
  repository: true, root: "/work/shop", branch: "main", detached: false, upstream: "origin/main",
  ahead: 0, behind: 0, files: [], truncated: false,
};
const feature: RepoStatus = { ...main, branch: "feature/x", upstream: "" };
const BOTH_MOVED = "This branch and its remote have both moved. Merge or rebase with your own git tool, then come back.";

function hook() {
  const onMoved = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const rendered = renderHook(() => useRepo("p1", onMoved), { wrapper });
  return { ...rendered, onMoved };
}

beforeEach(() => {
  api.getRepo.mockReset();
  api.getRepo.mockResolvedValue(main);
});

it("loads the repository status", async () => {
  const { result } = hook();

  await waitFor(() => expect(result.current.repo).toEqual(main));
  expect(api.getRepo).toHaveBeenCalledWith("p1");
  expect(result.current.busy).toBe(false);
  expect(result.current.error).toBeNull();
});

it("replaces the status with the one a verb answers, and reports a move only when asked", async () => {
  const { result, onMoved } = hook();
  await waitFor(() => expect(result.current.repo).toEqual(main));

  let done = false;
  await act(async () => {
    done = await result.current.act(async () => ({ ...main, ahead: 1 }));
  });
  expect(done).toBe(true);
  expect(result.current.repo?.ahead).toBe(1);
  expect(onMoved).not.toHaveBeenCalled();

  await act(async () => {
    done = await result.current.act(async () => feature, true);
  });
  expect(done).toBe(true);
  expect(result.current.repo).toEqual(feature);
  expect(onMoved).toHaveBeenCalledTimes(1);
});

it("keeps the previous status after a refusal and says why until dismissed", async () => {
  const { result, onMoved } = hook();
  await waitFor(() => expect(result.current.repo).toEqual(main));

  let done = true;
  await act(async () => {
    done = await result.current.act(() => Promise.reject(new ApiError(400, BOTH_MOVED)), true);
  });

  expect(done).toBe(false);
  expect(result.current.repo).toEqual(main);
  expect(result.current.error).toBe(BOTH_MOVED);
  expect(result.current.busy).toBe(false);
  expect(onMoved).not.toHaveBeenCalled();

  act(() => result.current.dismissError());
  expect(result.current.error).toBeNull();
});

it("drops the previous refusal when the next action starts", async () => {
  const { result } = hook();
  await waitFor(() => expect(result.current.repo).toEqual(main));
  await act(async () => {
    await result.current.act(() => Promise.reject(new ApiError(409, "A database change is running on this repository. Wait for it to finish.")));
  });
  expect(result.current.error).toMatch(/Wait for it to finish/);

  await act(async () => {
    await result.current.act(async () => main);
  });

  expect(result.current.error).toBeNull();
});

it("ignores a second action while one runs", async () => {
  const { result } = hook();
  await waitFor(() => expect(result.current.repo).toEqual(main));
  let finish: (status: RepoStatus) => void = () => {};
  let first: Promise<boolean> = Promise.resolve(false);
  act(() => {
    first = result.current.act(() => new Promise<RepoStatus>((resolve) => (finish = resolve)));
  });
  await waitFor(() => expect(result.current.busy).toBe(true));

  const second = vi.fn(async () => feature);
  let done = true;
  await act(async () => {
    done = await result.current.act(second);
  });
  expect(done).toBe(false);
  expect(second).not.toHaveBeenCalled();

  await act(async () => {
    finish({ ...main, ahead: 2 });
    await first;
  });
  expect(result.current.busy).toBe(false);
  expect(result.current.repo?.ahead).toBe(2);
});

it("reads the status again on demand", async () => {
  const { result } = hook();
  await waitFor(() => expect(result.current.repo).toEqual(main));
  api.getRepo.mockResolvedValue(feature);

  act(() => result.current.refresh());

  await waitFor(() => expect(result.current.repo).toEqual(feature));
});
