import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { ScriptFile } from "../api/types";
import ScriptPanel from "./ScriptPanel";

vi.mock("./CodeEditor", () => ({
  default: ({ value, onChange, label, readOnly }: { value: string; onChange: (v: string) => void; label: string; readOnly?: boolean }) => (
    <textarea aria-label={label} value={value} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
  ),
}));
const api = vi.hoisted(() => ({ readScript: vi.fn(), saveScript: vi.fn() }));
vi.mock("../api/scripts", () => api);
const git = vi.hoisted(() => ({ scriptDiff: vi.fn() }));
vi.mock("../api/git", () => git);

const V = "V1_0_1__create_orders.sql";
const U = "U1_0_1__create_orders.sql";
const file = (name: string, content: string): ScriptFile => ({
  name, kind: name.startsWith("U") ? "undo" : "versioned", version: "1.0.1", description: "create_orders",
  language: "sql", directory: "migrations", has_undo: true, path: "", change: "", undo_path: "", undo_change: "", content,
});

function panel(overrides: Partial<Parameters<typeof ScriptPanel>[0]> = {}) {
  const props = {
    projectId: "p1", script: V, applied: false, hasUndo: true, locked: false,
    onClose: vi.fn(), onSaved: vi.fn(), ...overrides,
  };
  render(<ScriptPanel {...props} />);
  return props;
}

beforeEach(() => {
  api.readScript.mockReset();
  api.saveScript.mockReset();
  api.readScript.mockImplementation(async (_p: string, name: string) =>
    name === V ? file(V, "CREATE TABLE orders (id INTEGER);\n") : file(U, "DROP TABLE orders;\n"),
  );
  api.saveScript.mockResolvedValue(file(V, ""));
  git.scriptDiff.mockReset();
});

it("opens the migration and lets the user edit and save it", async () => {
  const props = panel();
  const editor = await screen.findByLabelText(`Content of ${V}`);
  expect(editor).toHaveValue("CREATE TABLE orders (id INTEGER);\n");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

  await userEvent.type(editor, "-- note");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() => expect(api.saveScript).toHaveBeenCalledWith("p1", V, "CREATE TABLE orders (id INTEGER);\n-- note"));
  await waitFor(() => expect(props.onSaved).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

it("shows the undo script on its tab", async () => {
  panel();
  await screen.findByLabelText(`Content of ${V}`);

  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));

  expect(await screen.findByLabelText(`Content of ${U}`)).toHaveValue("DROP TABLE orders;\n");
});

it("says so when the migration has no undo script", async () => {
  api.readScript.mockImplementation(async (_p: string, name: string) => {
    if (name === V) {
      return file(V, "CREATE TABLE orders (id INTEGER);\n");
    }
    throw new ApiError(404, `no script named ${name}`);
  });
  panel({ hasUndo: false });
  await screen.findByLabelText(`Content of ${V}`);

  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));

  expect(await screen.findByText("This migration has no undo script.")).toBeInTheDocument();
});

it("warns before editing an applied migration", async () => {
  panel({ applied: true });
  await screen.findByLabelText(`Content of ${V}`);

  expect(screen.getByRole("note")).toHaveTextContent(/already applied/i);
  expect(screen.getByRole("note")).toHaveTextContent(/checksum/i);
});

it("does not warn on the undo tab of an applied migration", async () => {
  panel({ applied: true });
  await screen.findByLabelText(`Content of ${V}`);
  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));
  await screen.findByLabelText(`Content of ${U}`);

  expect(screen.queryByRole("note")).not.toBeInTheDocument();
});

it("asks before discarding unsaved edits when switching tab", async () => {
  panel();
  await userEvent.type(await screen.findByLabelText(`Content of ${V}`), "x");

  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByLabelText(`Content of ${V}`)).toHaveValue("CREATE TABLE orders (id INTEGER);\nx");

  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(await screen.findByLabelText(`Content of ${U}`)).toBeInTheDocument();
});

it("asks before closing with unsaved edits, and closes at once without", async () => {
  const props = panel();
  await screen.findByLabelText(`Content of ${V}`);
  await userEvent.click(screen.getByRole("button", { name: "Close editor" }));
  expect(props.onClose).toHaveBeenCalledTimes(1);

  await userEvent.type(screen.getByLabelText(`Content of ${V}`), "x");
  await userEvent.click(screen.getByRole("button", { name: "Close editor" }));
  expect(props.onClose).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "Discard" }));
  expect(props.onClose).toHaveBeenCalledTimes(2);
});

it("cannot save while a change is running", async () => {
  panel({ locked: true });
  await userEvent.type(await screen.findByLabelText(`Content of ${V}`), "x");

  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByText(/A change is running/)).toBeInTheDocument();
});

it("shows why a save failed and keeps the edits", async () => {
  api.saveScript.mockRejectedValue(new ApiError(400, "the content is too large to save here"));
  const props = panel();
  await userEvent.type(await screen.findByLabelText(`Content of ${V}`), "x");

  await userEvent.click(screen.getByRole("button", { name: "Save" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("the content is too large to save here");
  expect(screen.getByLabelText(`Content of ${V}`)).toHaveValue("CREATE TABLE orders (id INTEGER);\nx");
  expect(props.onSaved).not.toHaveBeenCalled();
});

it("lets the browser ask before leaving the page only while there are unsaved edits", async () => {
  const leavingIsStopped = () => {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  panel();
  const editor = await screen.findByLabelText(`Content of ${V}`);
  expect(leavingIsStopped()).toBe(false);

  await userEvent.type(editor, "x");
  expect(leavingIsStopped()).toBe(true);

  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(leavingIsStopped()).toBe(false));
});

it("cannot save while the SQL preview is open, and says why", async () => {
  panel({ previewing: true });
  await screen.findByLabelText(`Content of ${V}`);

  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(screen.getByText(/Close the SQL preview before editing/)).toBeInTheDocument();
  expect(screen.queryByText(/A change is running/)).not.toBeInTheDocument();
});

it("offers the changes only for a file that is not committed as it is", async () => {
  panel({ changed: [] });
  await screen.findByLabelText(`Content of ${V}`);
  expect(screen.queryByRole("button", { name: "Changes" })).not.toBeInTheDocument();
});

it("offers the changes of the migration, and of its undo script on its tab", async () => {
  panel({ changed: [U] });
  await screen.findByLabelText(`Content of ${V}`);
  expect(screen.queryByRole("button", { name: "Changes" })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("tab", { name: "Undo script" }));
  await screen.findByLabelText(`Content of ${U}`);

  expect(screen.getByRole("button", { name: "Changes" })).toBeInTheDocument();
});

it("shows the changes since the last commit, then the editor again", async () => {
  git.scriptDiff.mockResolvedValue("--- a/migrations/V.sql\n+++ b/migrations/V.sql\n@@ -1 +1,2 @@\n CREATE TABLE orders (id INTEGER);\n+-- note\n");
  panel({ changed: [V] });
  await screen.findByLabelText(`Content of ${V}`);

  await userEvent.click(screen.getByRole("button", { name: "Changes" }));

  expect(git.scriptDiff).toHaveBeenCalledWith("p1", V);
  const diff = await screen.findByLabelText("Changes since the last commit");
  expect(within(diff).getByText("+-- note")).toHaveClass("diff-add");
  expect(screen.getByRole("button", { name: "Changes" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByLabelText(`Content of ${V}`)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  expect(await screen.findByLabelText(`Content of ${V}`)).toBeInTheDocument();
});

it("says when the file has no change since the last commit", async () => {
  git.scriptDiff.mockResolvedValue("");
  panel({ changed: [V] });
  await screen.findByLabelText(`Content of ${V}`);

  await userEvent.click(screen.getByRole("button", { name: "Changes" }));

  expect(await screen.findByText("No change since the last commit.")).toBeInTheDocument();
});

it("says why the changes could not be read", async () => {
  git.scriptDiff.mockRejectedValue(new ApiError(400, "This project is not in a git repository."));
  panel({ changed: [V] });
  await screen.findByLabelText(`Content of ${V}`);

  await userEvent.click(screen.getByRole("button", { name: "Changes" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("not in a git repository");
});

it("keeps unsaved edits while the changes are shown", async () => {
  git.scriptDiff.mockResolvedValue("");
  panel({ changed: [V] });
  await userEvent.type(await screen.findByLabelText(`Content of ${V}`), "x");

  await userEvent.click(screen.getByRole("button", { name: "Changes" }));
  await screen.findByText("No change since the last commit.");
  await userEvent.click(screen.getByRole("button", { name: "Changes" }));

  expect(await screen.findByLabelText(`Content of ${V}`)).toHaveValue("CREATE TABLE orders (id INTEGER);\nx");
});
