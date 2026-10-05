import { execFileSync } from "node:child_process";

import { expect, type Page, test } from "@playwright/test";

import { FIXTURES } from "./paths";

// The scenarios run in file order on one server and use only the "gitapp" repository, whose
// remote is the bare repository "gitapp.git" beside it: each one starts from the state the one
// before it left.

const REPOSITORY = `${FIXTURES}/gitapp`;
const REMOTE = `${FIXTURES}/gitapp.git`;

/** The commit a reference points to, or "" when it does not exist. */
function commitOf(gitDir: string, ref: string): string {
  try {
    return execFileSync("git", ["--git-dir", gitDir, "rev-parse", "--verify", "--quiet", ref], { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

const chip = (page: Page) => page.getByRole("button", { name: /^Branch / });
const menu = (page: Page) => page.getByRole("dialog", { name: "Branch", exact: true });
// The repository's root project, not "gitapp · reporting" once that one is added.
const rootProject = (page: Page) => page.getByRole("button", { name: /^gitapp(?! ·)/ });

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
  await rootProject(page).click();
  await expect(page.getByRole("heading", { name: "gitapp", exact: true })).toBeVisible();
});

test("create a branch, commit the new migration on it, publish the branch", async ({ page }) => {
  await expect(chip(page)).toHaveAccessibleName("Branch main");
  await expect(chip(page)).not.toContainText("uncommitted");

  await page.getByRole("button", { name: "New migration" }).click();
  await page.getByLabel("What does it change?").fill("add thing");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByLabel("Content of V1_0_1__add_thing.sql")).toBeVisible();
  // The migration and its undo script are both new files.
  await expect(page.getByRole("row", { name: /add thing/ })).toContainText("Uncommitted");
  await expect(chip(page)).toContainText("2 uncommitted");

  await chip(page).click();
  await menu(page).getByRole("textbox", { name: "New branch" }).fill("feature/add-thing");
  await menu(page).getByRole("button", { name: "Create", exact: true }).click();
  await expect(menu(page)).toBeHidden();
  await expect(chip(page)).toHaveAccessibleName("Branch feature/add-thing");
  // The new files came along.
  await expect(chip(page)).toContainText("2 uncommitted");

  await chip(page).click();
  await menu(page).getByRole("button", { name: "Commit…" }).click();
  const dialog = page.getByRole("dialog", { name: "Commit", exact: true });
  await expect(dialog.getByRole("checkbox", { name: "migrations/V1_0_1__add_thing.sql" })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: "migrations/U1_0_1__add_thing.sql" })).toBeChecked();
  await dialog.getByLabel("Message").fill("Add thing");
  await dialog.getByRole("button", { name: "Commit 2 files" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByRole("row", { name: /add thing/ })).not.toContainText("Uncommitted");
  await expect(chip(page)).not.toContainText("uncommitted");
  expect(commitOf(REMOTE, "refs/heads/feature/add-thing")).toBe("");

  // A branch with no remote one yet is published to origin.
  await chip(page).click();
  await menu(page).getByRole("button", { name: "Publish branch" }).click();
  await expect(menu(page)).toBeHidden();
  await expect(chip(page)).not.toHaveAttribute("aria-busy", "true");
  await chip(page).click();
  await expect(menu(page).getByRole("button", { name: "Push", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(menu(page)).toBeHidden();
  await expect(chip(page)).not.toContainText("↑");

  const published = commitOf(REMOTE, "refs/heads/feature/add-thing");
  expect(published).not.toBe("");
  expect(published).toBe(commitOf(`${REPOSITORY}/.git`, "HEAD"));
});

test("an edited script shows its changes since the last commit", async ({ page }) => {
  await page.getByRole("button", { name: "Open V1_0_0__create_accounts.sql" }).click();
  const editor = page.getByLabel("Content of V1_0_0__create_accounts.sql");
  await expect(editor).toHaveText("CREATE TABLE accounts (id INTEGER PRIMARY KEY);");
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT);");
  await expect(editor).toHaveText("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT);");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();

  await expect(page.getByRole("row", { name: /create accounts/ })).toContainText("Uncommitted");
  await expect(chip(page)).toContainText("1 uncommitted");

  await page.getByRole("button", { name: "Changes" }).click();
  const changes = page.getByRole("region", { name: "Changes since the last commit" });
  await expect(changes.locator(".diff-add")).toHaveText("+CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT);");
  await expect(changes.locator(".diff-del")).toHaveText("-CREATE TABLE accounts (id INTEGER PRIMARY KEY);");
  await expect(editor).toHaveCount(0);

  await page.getByRole("button", { name: "Changes" }).click();
  await expect(changes).toHaveCount(0);
  await expect(editor).toBeVisible();
});

test("switch to a remote branch, add the config it brings, then come back", async ({ page }) => {
  // The edit of the scenario before is still uncommitted.
  await expect(chip(page)).toContainText("1 uncommitted");
  await chip(page).click();
  await expect(menu(page).getByText("1 uncommitted file will come along if git allows it.")).toBeVisible();
  await menu(page).getByRole("button", { name: "origin/feature/reporting", exact: true }).click();

  await expect(chip(page)).toHaveAccessibleName("Branch feature/reporting");
  await expect(chip(page)).toContainText("1 uncommitted");
  // The migration committed on feature/add-thing is not on this branch.
  await expect(page.getByRole("row", { name: /add thing/ })).toHaveCount(0);

  const notice = page.getByRole("status").filter({ hasText: "on this branch" });
  await expect(notice).toContainText("1 configuration on this branch is not a project yet.");
  await notice.getByRole("button", { name: "Add" }).click();

  const add = page.getByRole("dialog", { name: "Add project" });
  await expect(add.getByRole("checkbox", { name: "reporting/dblift.yaml" })).toBeChecked();
  await expect(add.getByRole("checkbox", { name: "dblift.yaml", exact: true })).toBeDisabled();
  await add.getByRole("button", { name: "Add 1 project" }).click();
  await expect(add).toBeHidden();
  await expect(notice).toHaveCount(0);

  const group = page.getByRole("group", { name: "gitapp" });
  await expect(group.getByRole("button", { name: /^gitapp/ })).toHaveCount(2);
  const reporting = group.getByRole("button", { name: /^gitapp · reporting/ });
  await expect(reporting).not.toContainText("not on this branch");

  await rootProject(page).click();
  await chip(page).click();
  await menu(page).getByRole("button", { name: "main", exact: true }).click();
  await expect(chip(page)).toHaveAccessibleName("Branch main");
  await expect(reporting).toContainText("not on this branch");
  await expect(rootProject(page)).not.toContainText("not on this branch");
});

test("a refused branch name is explained and changes nothing", async ({ page }) => {
  await chip(page).click();
  await menu(page).getByRole("textbox", { name: "New branch" }).fill("-x");
  await menu(page).getByRole("button", { name: "Create", exact: true }).click();

  const refusal = page.getByRole("alert").filter({ hasText: "not a branch name" });
  await expect(refusal).toBeVisible();
  await expect(chip(page)).toHaveAccessibleName("Branch main");
  expect(commitOf(`${REPOSITORY}/.git`, "refs/heads/-x")).toBe("");

  await refusal.getByRole("button", { name: "Dismiss" }).click();
  await expect(refusal).toHaveCount(0);
});
