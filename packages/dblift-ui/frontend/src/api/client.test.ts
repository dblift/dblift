import { afterEach, expect, it, vi } from "vitest";

import { ApiError, request, TOKEN_HEADER } from "./client";

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
