import { expect, it } from "vitest";

import { getToken, takeToken } from "./token";

it("moves the token from the address bar to session storage", () => {
  window.history.replaceState(null, "", "/?token=abc123&keep=1#top");

  expect(takeToken()).toBe("abc123");

  expect(window.location.search).toBe("?keep=1");
  expect(window.location.hash).toBe("#top");
  expect(getToken()).toBe("abc123");
});

it("keeps the stored token when the address has none", () => {
  window.history.replaceState(null, "", "/?token=first");
  takeToken();
  window.history.replaceState(null, "", "/");

  expect(takeToken()).toBe("first");
});

it("returns an empty string when there is no token anywhere", () => {
  window.history.replaceState(null, "", "/");
  expect(takeToken()).toBe("");
  expect(getToken()).toBe("");
});
