// The browser tests run in Node; the project's types are the browser's, so declare the few Node functions used here.
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
}

declare module "node:child_process" {
  export function execFileSync(file: string, args: string[], options: { encoding: "utf8" }): string;
}
