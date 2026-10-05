import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Script, ScratchResult } from "../../api/types";
import { renderStep, U, V } from "../../test/wizard";
import WriteStep from "./WriteStep";

vi.mock("../CodeEditor", () => ({
  default: ({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) => (
    <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));
const scripts = vi.hoisted(() => ({ listScripts: vi.fn(), readScript: vi.fn(), saveScript: vi.fn(), createScripts: vi.fn() }));
vi.mock("../../api/scripts", () => scripts);
const git = vi.hoisted(() => ({ getRepo: vi.fn() }));
vi.mock("../../api/git", () => git);

function file(name: string): Script {
  return {
    name, kind: name.startsWith("U") ? "undo" : "versioned", version: "1.0.2", description: "add invoices", language: "sql", directory: "migrations",
    has_undo: true, path: "", change: "", undo_path: "", undo_change: "",
  };
}
const passed: ScratchResult = { strategy: "file", passed: true, skipped: false, phases: [], script: V };
const created = { scripts: { migration: V, undo: U }, description: "Add invoices" };

beforeEach(() => {
  Object.values(scripts).forEach((mock) => mock.mockReset());
  scripts.readScript.mockImplementation(async (_p: string, name: string) => ({ ...file(name), content: `-- ${name}\n` }));
  scripts.saveScript.mockImplementation(async (_p: string, name: string) => file(name));
  git.getRepo.mockResolvedValue({ repository: false });
});

const migration = () => screen.findByRole("textbox", { name: `Content of ${V}` });
const undo = () => screen.findByRole("textbox", { name: `Content of ${U}` });
const next = () => screen.getByRole("button", { name: "Next" });

it("shows the migration and its undo script side by side, each titled with its file name", async () => {
  renderStep(WriteStep, { data: created });

  const left = screen.getByRole("region", { name: "Migration" });
  const right = screen.getByRole("region", { name: "Undo script" });
  expect(left).toHaveTextContent(V);
  expect(right).toHaveTextContent(U);
  expect(await migration()).toHaveValue(`-- ${V}\n`);
  expect(await undo()).toHaveValue(`-- ${U}\n`);
  expect(scripts.readScript).toHaveBeenCalledWith("p1", V);
  expect(scripts.readScript).toHaveBeenCalledWith("p1", U);
});

it("says under the undo editor what the undo script must do", () => {
  renderStep(WriteStep, { data: created });

  expect(screen.getByRole("region", { name: "Undo script" })).toHaveTextContent(
    "The undo script must leave the database as it was before the migration.",
  );
});

it("saves both scripts on Next when they changed, then moves on and has the view behind re-read", async () => {
  const { onNext, changed, context } = renderStep(WriteStep, { data: created });
  await userEvent.type(await migration(), "CREATE TABLE invoices (id INTEGER PRIMARY KEY);");
  await userEvent.type(await undo(), "DROP TABLE invoices;");

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(scripts.saveScript).toHaveBeenCalledWith("p1", V, `-- ${V}\nCREATE TABLE invoices (id INTEGER PRIMARY KEY);`);
  expect(scripts.saveScript).toHaveBeenCalledWith("p1", U, `-- ${U}\nDROP TABLE invoices;`);
  expect(changed).toHaveBeenCalled();
  expect(context().written).toBe(true);
  expect(context().unsaved).toBe(false);
});

it("saves only the script that changed", async () => {
  const { onNext } = renderStep(WriteStep, { data: created });
  await userEvent.type(await undo(), "DROP TABLE invoices;");

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(scripts.saveScript).toHaveBeenCalledTimes(1);
  expect(scripts.saveScript).toHaveBeenCalledWith("p1", U, `-- ${U}\nDROP TABLE invoices;`);
});

it("saves nothing and keeps the test's outcome when nothing changed", async () => {
  const { onNext, context } = renderStep(WriteStep, { data: { ...created, test: { outcome: "passed", result: passed } } });
  await migration();

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(scripts.saveScript).not.toHaveBeenCalled();
  expect(context().test.outcome).toBe("passed");
  expect(context().written).toBe(true);
});

it("forgets the test's outcome and the commit once a changed script is saved", async () => {
  const { onNext, context } = renderStep(WriteStep, {
    data: { ...created, test: { outcome: "passed", result: passed }, committed: true, published: true },
  });
  await userEvent.type(await migration(), "-- more");

  await userEvent.click(next());

  await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  expect(context().test).toEqual({ outcome: null, result: passed });
  expect(context().committed).toBe(false);
  expect(context().published).toBe(false);
});

it("tells the wizard about unsaved edits", async () => {
  const { context } = renderStep(WriteStep, { data: created });
  expect(context().unsaved).toBe(false);

  await userEvent.type(await undo(), "x");

  expect(context().unsaved).toBe(true);
});

it("disables Next while saving", async () => {
  let finish: () => void = () => {};
  scripts.saveScript.mockImplementation(() => new Promise<Script>((resolve) => (finish = () => resolve(file(V)))));
  renderStep(WriteStep, { data: created });
  await userEvent.type(await migration(), "x");

  await userEvent.click(next());

  expect(next()).toBeDisabled();
  finish();
  await waitFor(() => expect(next()).toBeEnabled());
});

it("shows a refused save and stays", async () => {
  scripts.saveScript.mockRejectedValue(new Error("A change is running on this project. Save once it has finished."));
  const { onNext, context } = renderStep(WriteStep, { data: created });
  await userEvent.type(await migration(), "x");

  await userEvent.click(next());

  expect(await screen.findByRole("alert")).toHaveTextContent("A change is running on this project. Save once it has finished.");
  expect(onNext).not.toHaveBeenCalled();
  expect(context().written).toBe(false);
  expect(await migration()).toHaveValue(`-- ${V}\nx`);
});

it("goes back", async () => {
  const { onBack } = renderStep(WriteStep, { data: created });

  await userEvent.click(screen.getByRole("button", { name: "Back" }));

  expect(onBack).toHaveBeenCalledTimes(1);
});

it("says when the files cannot be read", async () => {
  scripts.readScript.mockRejectedValue(new Error("permission denied"));
  renderStep(WriteStep, { data: created });

  expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("permission denied");
});

let keys: string[];
const listen = (event: KeyboardEvent) => keys.push(event.key);
afterEach(() => window.removeEventListener("keydown", listen));

it("keeps Escape in an editor for the editor, so it does not close the wizard", async () => {
  keys = [];
  window.addEventListener("keydown", listen);
  renderStep(WriteStep, { data: created });

  fireEvent.keyDown(await migration(), { key: "Escape" });
  fireEvent.keyDown(screen.getByRole("button", { name: "Back" }), { key: "Escape" });

  expect(keys).toEqual(["Escape"]);
});
