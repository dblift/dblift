// The browser tests run in Node; the project's types are the browser's, so declare the one Node function used here.
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf8"): string;
}
