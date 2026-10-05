import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import DiffView from "./DiffView";

const diff = [
  "diff --git a/migrations/V1_0_0__create_accounts.sql b/migrations/V1_0_0__create_accounts.sql",
  "index 3b18e51..a5c1f2d 100644",
  "--- a/migrations/V1_0_0__create_accounts.sql",
  "+++ b/migrations/V1_0_0__create_accounts.sql",
  "@@ -1,3 +1,4 @@",
  " CREATE TABLE accounts (",
  "-  id INTEGER",
  "+  id INTEGER,",
  "+  email TEXT",
  " );",
  "",
].join("\n");

const lines = () => [...screen.getByLabelText("Changes since the last commit").children] as HTMLElement[];

it("marks added, removed and hunk lines", () => {
  render(<DiffView diff={diff} />);

  const added = lines().filter((l) => l.classList.contains("diff-add")).map((l) => l.textContent);
  const removed = lines().filter((l) => l.classList.contains("diff-del")).map((l) => l.textContent);
  const hunks = lines().filter((l) => l.classList.contains("diff-hunk")).map((l) => l.textContent);
  expect(added).toEqual(["+  id INTEGER,", "+  email TEXT"]);
  expect(removed).toEqual(["-  id INTEGER"]);
  expect(hunks).toEqual(["@@ -1,3 +1,4 @@"]);
  expect(lines().find((l) => l.textContent === " CREATE TABLE accounts (")?.className).not.toMatch(/diff-(add|del|hunk)/);
});

it("does not show the header lines", () => {
  render(<DiffView diff={diff} />);

  const shown = lines().map((l) => l.textContent ?? "");
  expect(shown.some((text) => text.startsWith("diff --git"))).toBe(false);
  expect(shown.some((text) => text.startsWith("index "))).toBe(false);
  expect(shown.some((text) => text.startsWith("---"))).toBe(false);
  expect(shown.some((text) => text.startsWith("+++"))).toBe(false);
  expect(shown[0]).toBe("@@ -1,3 +1,4 @@");
});

it("is a block of preformatted text named after what it shows", () => {
  render(<DiffView diff={diff} />);

  expect(screen.getByLabelText("Changes since the last commit").tagName).toBe("PRE");
});

it("renders the text as text, never as markup", () => {
  render(<DiffView diff={"@@ -0,0 +1 @@\n+<script>alert(1)</script>\n"} />);

  expect(screen.getByText("+<script>alert(1)</script>")).toHaveClass("diff-add");
  expect(document.querySelector("pre script")).toBeNull();
});

it("shows a removed SQL comment inside a hunk as a removed line", () => {
  render(<DiffView diff={"--- a/x.sql\n+++ b/x.sql\n@@ -1,2 +1,2 @@\n--- old note\n+-- new note\n++++ plus\n SELECT 1;\n"} />);

  expect(screen.getByText("--- old note")).toHaveClass("diff-del");
  expect(screen.getByText("+-- new note")).toHaveClass("diff-add");
  expect(screen.getByText("++++ plus")).toHaveClass("diff-add");
});

it("hides the header of a new file", () => {
  render(<DiffView diff={"diff --git a/V2.sql b/V2.sql\nnew file mode 100644\nindex 0000000..e69de29\n--- /dev/null\n+++ b/V2.sql\n@@ -0,0 +1 @@\n+SELECT 1;\n"} />);

  expect(lines().map((l) => l.textContent)).toEqual(["@@ -0,0 +1 @@", "+SELECT 1;"]);
});

it("says so when a change has no lines to show", () => {
  render(<DiffView diff={"diff --git a/V1.sql b/V1.sql\nold mode 100644\nnew mode 100755\n"} />);

  expect(screen.getByText("This change cannot be shown as text.")).toBeVisible();
  expect(screen.queryByLabelText("Changes since the last commit")).toBeNull();

  render(<DiffView diff={"diff --git a/V2.sql b/V2.sql\nindex 3b18e51..a5c1f2d 100644\nBinary files a/V2.sql and b/V2.sql differ\n"} />);
  expect(screen.getAllByText("This change cannot be shown as text.")).toHaveLength(2);
});
