import { afterEach, expect, it, vi } from "vitest";

import { ApiError, request, requestText, TOKEN_HEADER } from "./client";

function respond(status: number, body: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

afterEach(() => vi.unstubAllGlobals());

it("sends the token header and returns the JSON body", async () => {
  sessionStorage.setItem("dblift-ui-token", "tok");
  const fetchMock = vi.fn().mockResolvedValue(respond(200, [{ id: "1" }]));
  vi.stubGlobal("fetch", fetchMock);

  const body = await request<{ id: string }[]>("/projects");

  expect(body).toEqual([{ id: "1" }]);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/projects");
  expect(init.headers[TOKEN_HEADER]).toBe("tok");
});

it("turns an error response into an ApiError carrying the server's detail", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(400, { detail: "config file not found" })));

  const failure = (await request("/projects", { method: "POST" }).catch((e) => e)) as ApiError;

  expect(failure).toBeInstanceOf(ApiError);
  expect(failure.status).toBe(400);
  expect(failure.message).toBe("config file not found");
});

it("returns undefined for an empty 204 response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(204, undefined)));

  expect(await request<void>("/projects/1", { method: "DELETE" })).toBeUndefined();
});

it("returns text bodies as they are and still sends the token", async () => {
  sessionStorage.setItem("dblift-ui-token", "tok");
  const fetchMock = vi.fn().mockResolvedValue(new Response("line 1\nline 2\n", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);

  expect(await requestText("/jobs/j1/log")).toBe("line 1\nline 2\n");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs/j1/log");
  expect(fetchMock.mock.calls[0][1].headers[TOKEN_HEADER]).toBe("tok");
});

it("turns a failed text request into an ApiError", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "this job has no log" }), { status: 404 })));

  const failure = (await requestText("/jobs/j1/log").catch((e) => e)) as ApiError;

  expect(failure).toBeInstanceOf(ApiError);
  expect(failure.status).toBe(404);
  expect(failure.message).toBe("this job has no log");
});
