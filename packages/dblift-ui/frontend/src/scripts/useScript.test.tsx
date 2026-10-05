import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { ScriptFile } from "../api/types";
import { useScript } from "./useScript";

const api = vi.hoisted(() => ({ readScript: vi.fn(), saveScript: vi.fn() }));
vi.mock("../api/scripts", () => api);

const file: ScriptFile = {
  name: "V1_0_0__a.sql", kind: "versioned", version: "1.0.0", description: "a", language: "sql",
  directory: "migrations", has_undo: true, path: "", change: "", undo_path: "", undo_change: "", content: "CREATE TABLE a (id INTEGER);\n",
};

beforeEach(() => {
  api.readScript.mockReset();
  api.saveScript.mockReset();
});

it("loads a script", async () => {
  api.readScript.mockResolvedValue(file);
  const { result } = renderHook(() => useScript("p1", "V1_0_0__a.sql"));

  expect(result.current.phase).toBe("loading");
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  expect(result.current.content).toBe(file.content);
  expect(result.current.dirty).toBe(false);
  expect(api.readScript).toHaveBeenCalledWith("p1", "V1_0_0__a.sql");
});

it("is idle without a name", () => {
  const { result } = renderHook(() => useScript("p1", null));
  expect(result.current.phase).toBe("idle");
  expect(api.readScript).not.toHaveBeenCalled();
});

it("tracks edits and saves them", async () => {
  api.readScript.mockResolvedValue(file);
  api.saveScript.mockResolvedValue({ ...file });
  const { result } = renderHook(() => useScript("p1", "V1_0_0__a.sql"));
  await waitFor(() => expect(result.current.phase).toBe("ready"));

  act(() => result.current.edit("CREATE TABLE a (id INTEGER, name TEXT);\n"));
  expect(result.current.dirty).toBe(true);

  let saved = false;
  await act(async () => {
    saved = await result.current.save();
  });

  expect(saved).toBe(true);
  expect(api.saveScript).toHaveBeenCalledWith("p1", "V1_0_0__a.sql", "CREATE TABLE a (id INTEGER, name TEXT);\n");
  expect(result.current.dirty).toBe(false);
  expect(result.current.error).toBeNull();
});

it("is not dirty when an edit restores the saved content", async () => {
  api.readScript.mockResolvedValue(file);
  const { result } = renderHook(() => useScript("p1", "V1_0_0__a.sql"));
  await waitFor(() => expect(result.current.phase).toBe("ready"));

  act(() => result.current.edit("something else"));
  act(() => result.current.edit(file.content));

  expect(result.current.dirty).toBe(false);
});

it("keeps the edits and reports why a save failed", async () => {
  api.readScript.mockResolvedValue(file);
  api.saveScript.mockRejectedValue(new ApiError(409, "A change is running on this project. Save once it has finished."));
  const { result } = renderHook(() => useScript("p1", "V1_0_0__a.sql"));
  await waitFor(() => expect(result.current.phase).toBe("ready"));
  act(() => result.current.edit("edited"));

  let saved = true;
  await act(async () => {
    saved = await result.current.save();
  });

  expect(saved).toBe(false);
  expect(result.current.content).toBe("edited");
  expect(result.current.dirty).toBe(true);
  expect(result.current.error).toMatch(/A change is running/);
});

it("reports a script that does not exist as missing", async () => {
  api.readScript.mockRejectedValue(new ApiError(404, "no script named U1_0_0__a.sql"));
  const { result } = renderHook(() => useScript("p1", "U1_0_0__a.sql"));

  await waitFor(() => expect(result.current.phase).toBe("missing"));
});

it("reports other failures as errors", async () => {
  api.readScript.mockRejectedValue(new ApiError(400, "V1_0_0__a.sql is not UTF-8 text"));
  const { result } = renderHook(() => useScript("p1", "V1_0_0__a.sql"));

  await waitFor(() => expect(result.current.phase).toBe("error"));
  expect(result.current.error).toBe("V1_0_0__a.sql is not UTF-8 text");
});

it("loads the other script when the name changes and ignores a late answer", async () => {
  let finishFirst: (value: ScriptFile) => void = () => {};
  api.readScript
    .mockImplementationOnce(() => new Promise<ScriptFile>((resolve) => (finishFirst = resolve)))
    .mockResolvedValueOnce({ ...file, name: "U1_0_0__a.sql", kind: "undo", content: "DROP TABLE a;\n" });
  const { result, rerender } = renderHook(({ name }) => useScript("p1", name), {
    initialProps: { name: "V1_0_0__a.sql" as string | null },
  });

  rerender({ name: "U1_0_0__a.sql" });
  await waitFor(() => expect(result.current.content).toBe("DROP TABLE a;\n"));
  await act(async () => finishFirst(file));

  expect(result.current.content).toBe("DROP TABLE a;\n");
});
