const STORAGE_KEY = "dblift-ui-token";

/**
 * The launch URL carries the token once. Keep it for this tab only and take
 * it out of the address bar so it is not copied or bookmarked by accident.
 */
export function takeToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    sessionStorage.setItem(STORAGE_KEY, fromUrl);
    url.searchParams.delete("token");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  return getToken();
}

export function getToken(): string {
  return sessionStorage.getItem(STORAGE_KEY) ?? "";
}
