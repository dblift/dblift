import { expect, it } from "vitest";

import type { ChangedFile, Script } from "../api/types";
import { changedScriptFiles } from "./changes";

function script(name: string, path: string, change: string, undoPath = "", undoChange = ""): Script {
  return {
    name, kind: "versioned", version: "1", description: "", language: "sql", directory: "m", has_undo: undoPath !== "",
    path, change, undo_path: undoPath, undo_change: undoChange,
  };
}

it("gives the changed files that are these scripts or their undo scripts, by their exact paths, in the files' order", () => {
  const files: ChangedFile[] = [
    { path: "db/m/U1__a.sql", state: "untracked" },
    { path: "notes.txt", state: "modified" },
    { path: "db/m/V1__a.sql", state: "untracked" },
    { path: "db/m/V2__b.sql", state: "modified" },
  ];
  const scripts = [script("V1__a.sql", "db/m/V1__a.sql", "untracked", "db/m/U1__a.sql", "untracked")];

  expect(changedScriptFiles(files, scripts)).toEqual(["db/m/U1__a.sql", "db/m/V1__a.sql"]);
});

it("leaves out a script committed as it is, and a path that is not in the changed files", () => {
  const files: ChangedFile[] = [{ path: "db/m/U1__a.sql", state: "modified" }];
  const scripts = [script("V1__a.sql", "db/m/V1__a.sql", "", "db/m/U1__a.sql", "modified"), script("V2__b.sql", "db/m/V2__b.sql", "modified")];

  expect(changedScriptFiles(files, scripts)).toEqual(["db/m/U1__a.sql"]);
});
