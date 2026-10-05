import { expect, type Locator, type Page, test } from "@playwright/test";

// The scenarios run in file order on one server and use only the "notes" project:
// each one starts from the state the one before it left.

const stat = (page: Page, name: string) =>
  page.locator("dl.summary__stats div", { has: page.locator("dt", { hasText: name }) }).locator("dd");

const save = (page: Page) => page.getByRole("button", { name: "Save", exact: true });

/** Replaces the whole text of a code editor, the way a user does: select all, then type. */
async function replaceText(page: Page, editor: Locator, text: string) {
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type(text);
  await expect(editor).toHaveText(text);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
  await page.getByRole("button", { name: /^notes/ }).click();
});

test("write a new migration in the editor, apply it, read the full log", async ({ page }) => {
  await expect(stat(page, "Pending")).toHaveText("1");

  await page.getByRole("button", { name: "New migration" }).click();
  await page.getByLabel("What does it change?").fill("add tags");
  await page.getByRole("button", { name: "Create", exact: true }).click();

  const editor = page.getByLabel("Content of V1_0_1__add_tags.sql");
  await expect(editor).toHaveText("-- add tags");
  await replaceText(page, editor, "CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT);");
  await save(page).click();
  await expect(save(page)).toBeDisabled();

  await page.getByRole("tab", { name: "Undo script" }).click();
  const undo = page.getByLabel("Content of U1_0_1__add_tags.sql");
  await expect(undo).toHaveText("-- Undo: add tags");
  await replaceText(page, undo, "DROP TABLE tags;");
  await save(page).click();
  await expect(save(page)).toBeDisabled();
  await page.getByRole("button", { name: "Close editor" }).click();

  await expect(stat(page, "Pending")).toHaveText("2");
  await page.getByRole("button", { name: "Migrate" }).click();
  const preview = page.getByRole("region", { name: "SQL to be applied" });
  await expect(preview.getByText("CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT);")).toBeVisible();
  await preview.getByRole("button", { name: "Apply 2 migrations" }).click();

  await expect(page.getByRole("log").getByText("✓ done")).toBeVisible();
  await expect(stat(page, "Applied")).toHaveText("2");
  await expect(page.getByRole("row", { name: /add tags/ })).toContainText("Yes");

  // Reopened once applied, the new migration warns that editing it changes its checksum.
  await page.getByRole("button", { name: "Open V1_0_1__add_tags.sql" }).click();
  await expect(page.getByLabel("Content of V1_0_1__add_tags.sql")).toHaveText(
    "CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT);",
  );
  await expect(page.getByRole("note")).toContainText("already applied");
  await page.getByRole("button", { name: "Close editor" }).click();

  await page.getByRole("button", { name: "Full log" }).click();
  await expect(page.locator(".runlog__full")).toContainText("V1_0_1__add_tags.sql");

  await page.getByRole("button", { name: "Undo last migration" }).click();
  await page.getByRole("button", { name: "Confirm undo" }).click();
  await expect(page.getByRole("log").getByText("Reverted with U1_0_1__add_tags.sql")).toBeVisible();
  await expect(stat(page, "Applied")).toHaveText("1");
});

test("an applied migration opens with a warning", async ({ page }) => {
  await page.getByRole("button", { name: "Open V1_0_0__create_notes.sql" }).click();

  await expect(page.getByLabel("Content of V1_0_0__create_notes.sql")).toHaveText(
    "CREATE TABLE notes (id INTEGER PRIMARY KEY);",
  );
  await expect(page.getByRole("note")).toContainText("already applied");
});

test("nothing can be saved while the SQL preview is open", async ({ page }) => {
  // The first scenario undid 1.0.1, so it is pending again.
  await expect(stat(page, "Pending")).toHaveText("1");
  await page.getByRole("button", { name: "Open V1_0_1__add_tags.sql" }).click();
  const editor = page.getByLabel("Content of V1_0_1__add_tags.sql");
  await replaceText(page, editor, "CREATE TABLE tags (id INTEGER PRIMARY KEY);");
  await expect(save(page)).toBeEnabled();

  await page.getByRole("button", { name: "Migrate" }).click();
  const preview = page.getByRole("region", { name: "SQL to be applied" });
  // The preview shows the file as saved, not the edit in progress.
  await expect(preview.getByText("CREATE TABLE tags (id INTEGER PRIMARY KEY, label TEXT);")).toBeVisible();
  await expect(save(page)).toBeDisabled();
  await expect(editor).toHaveAttribute("aria-readonly", "true");

  await preview.getByRole("button", { name: "Cancel" }).click();
  await expect(preview).toHaveCount(0);
  await expect(save(page)).toBeEnabled();
  await expect(editor).not.toHaveAttribute("aria-readonly", "true");

  // Leave the file as it was.
  await page.getByRole("button", { name: "Close editor" }).click();
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(editor).toHaveCount(0);
});
