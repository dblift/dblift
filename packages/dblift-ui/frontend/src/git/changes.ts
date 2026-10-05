import type { ChangedFile, Script } from "../api/types";

/** The changed *files* that are these scripts or their undo scripts, by the exact paths the scripts list gives. */
export function changedScriptFiles(files: ChangedFile[], scripts: Script[]): string[] {
  const own = new Set(scripts.flatMap((s) => [s.change && s.path, s.undo_change && s.undo_path]).filter(Boolean));
  return files.filter((f) => own.has(f.path)).map((f) => f.path);
}
