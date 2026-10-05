import type { Discovery } from "../api/types";

/** Where a config sits, in words: its folder, or its file name when it is at the root. */
function where(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash < 0 ? path.replace(/\.ya?ml$/i, "") : path.slice(0, slash);
}

/** A name for each selected config: the folder's name, made distinct when there are several. */
export function defaultNames(discovery: Discovery, paths: string[]): Record<string, string> {
  if (paths.length === 1) {
    return { [paths[0]]: discovery.name };
  }
  return Object.fromEntries(paths.map((path) => [path, `${discovery.name} · ${where(path)}`]));
}
