import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

import { expect, type Locator, type Page, test } from "@playwright/test";

import { FIXTURES } from "./paths";

// The scenarios run in file order on one server and use the "wizardapp" repository, whose remote
// is the bare repository "wizardapp.git" beside it: each one starts from the state the one before
// it left. The last one reads a link for "wizardhub", whose origin is a GitHub address never contacted.

const REPOSITORY = `${FIXTURES}/wizardapp`;
const REMOTE = `${FIXTURES}/wizardapp.git`;

/** The commit a reference points to, or "" when it does not exist. */
function commitOf(gitDir: string, ref: string): string {
  try {
    return execFileSync("git", ["--git-dir", gitDir, "rev-parse", "--verify", "--quiet", ref], { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

/** Replaces the whole text of a code editor, the way a user does: select all, then type. */
async function replaceText(page: Page, editor: Locator, text: string) {
  await editor.click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type(text);
  await expect(editor).toHaveText(text);
}

const wizard = (page: Page) => page.getByRole("dialog", { name: "New change" });
const chip = (page: Page) => page.getByRole("button", { name: /^Branch / });
const heading = (page: Page, title: string) => wizard(page).getByRole("heading", { name: title, exact: true });
const phase = (page: Page, label: string) =>
  wizard(page).getByRole("list", { name: "Test phases" }).getByRole("listitem").filter({ hasText: label });
const next = (page: Page) => wizard(page).getByRole("button", { name: "Next", exact: true });
const stat = (page: Page, name: string) =>
  page.locator("dl.summary__stats div", { has: page.locator("dt", { hasText: name }) }).locator("dd");

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
  await page.getByRole("button", { name: /^wizardapp/ }).click();
  await expect(page.getByRole("heading", { name: "wizardapp", exact: true })).toBeVisible();
});

test("a change from description to published branch, with a broken undo caught and fixed", async ({ page }) => {
  await expect(chip(page)).toHaveAccessibleName("Branch main");
  // Reading the project's status creates its SQLite file: from here on, nothing may change it.
  await expect(stat(page, "Pending")).toHaveText("1");
  const database = readFileSync(`${REPOSITORY}/dev.db`);
  await page.getByRole("button", { name: "New change" }).click();

  // Describe: on main, a branch named after the description's first line is offered.
  await wizard(page).getByRole("textbox", { name: "What does this change do?" }).fill("Add invoices\n\nOne row per invoice sent.");
  await expect(wizard(page).getByRole("checkbox", { name: "Create a branch" })).toBeChecked();
  await expect(wizard(page).getByRole("textbox", { name: "Branch name" })).toHaveValue("feature/add-invoices");
  await next(page).click();

  // Write: the migration, and an undo script that names the wrong table.
  await expect(heading(page, "Write")).toBeFocused();
  await expect(chip(page)).toHaveAccessibleName("Branch feature/add-invoices");
  const migration = wizard(page).getByLabel("Content of V1_0_1__add_invoices.sql");
  const undo = wizard(page).getByLabel("Content of U1_0_1__add_invoices.sql");
  await replaceText(page, migration, "CREATE TABLE invoices (id INTEGER PRIMARY KEY);");
  await replaceText(page, undo, "DROP TABLE invoice;");
  await next(page).click();

  // Test: the plan says where it runs, and the broken undo fails with the database's own error.
  await expect(heading(page, "Test")).toBeFocused();
  await expect(wizard(page).getByText("A temporary SQLite database is created, used and deleted.")).toBeVisible();
  await wizard(page).getByRole("button", { name: "Run the test" }).click();
  await expect(phase(page, "Build from zero")).toContainText("passed");
  await expect(phase(page, "Undo the new migration")).toContainText("failed");
  await expect(phase(page, "Apply it again")).toContainText("skipped");
  const failure = wizard(page).getByRole("alert");
  await expect(failure).toContainText("Undo the new migration failed.");
  await expect(failure).toContainText("no such table: invoice");
  await expect(next(page)).toBeDisabled();
  // A failed run does not open the later steps.
  await expect(wizard(page).getByRole("navigation", { name: "Steps" }).getByRole("button", { name: "Commit" })).toBeDisabled();

  // Fix the undo script, then run again.
  await wizard(page).getByRole("button", { name: "Back to the scripts" }).click();
  await expect(heading(page, "Write")).toBeFocused();
  await replaceText(page, undo, "DROP TABLE invoices;");
  await next(page).click();
  await expect(wizard(page).getByRole("status")).toHaveText("The scripts changed since this run. Run the test again.");
  await wizard(page).getByRole("button", { name: "Run again" }).click();
  await expect(wizard(page).getByRole("status")).toHaveText("The test passed.");
  for (const label of ["Build from zero", "Undo the new migration", "Apply it again"]) {
    await expect(phase(page, label)).toContainText("passed");
  }
  await expect(wizard(page).getByRole("alert")).toHaveCount(0);
  await next(page).click();

  // Commit: the two scripts are ticked, the message is the description.
  await expect(heading(page, "Commit")).toBeFocused();
  await expect(wizard(page).getByRole("checkbox", { name: "migrations/V1_0_1__add_invoices.sql" })).toBeChecked();
  await expect(wizard(page).getByRole("checkbox", { name: "migrations/U1_0_1__add_invoices.sql" })).toBeChecked();
  await expect(wizard(page).getByRole("textbox", { name: "Message" })).toHaveValue("Add invoices");
  await wizard(page).getByRole("button", { name: "Commit 2 files" }).click();
  await expect(wizard(page).getByText("The scripts are committed on feature/add-invoices.")).toBeVisible();
  await next(page).click();

  // Publish: the remote is a local path, so there is no link, only the text to paste.
  await expect(heading(page, "Publish")).toBeFocused();
  expect(commitOf(REMOTE, "refs/heads/feature/add-invoices")).toBe("");
  await wizard(page).getByRole("button", { name: "Publish branch" }).click();
  await expect(wizard(page).getByRole("textbox", { name: "Pull request title" })).toHaveValue("Add invoices");
  const body = wizard(page).getByRole("textbox", { name: "Pull request description" });
  await expect(body).toHaveValue(/^## Change\nAdd invoices\n\nOne row per invoice sent\.\n/);
  await expect(body).toHaveValue(/V1_0_1__add_invoices\.sql/);
  await expect(body).toHaveValue(/Passed on a temporary SQLite database/);
  await expect(wizard(page).getByText("Open a pull request for feature/add-invoices on your git host")).toBeVisible();
  await expect(wizard(page).getByRole("link", { name: "Open the pull request page" })).toHaveCount(0);
  const published = commitOf(REMOTE, "refs/heads/feature/add-invoices");
  expect(published).not.toBe("");
  expect(published).toBe(commitOf(`${REPOSITORY}/.git`, "HEAD"));
  await wizard(page).getByRole("button", { name: "Finish" }).click();
  await expect(wizard(page)).toBeHidden();

  // Behind the wizard: the branch, the new migration pending and committed, the project's database untouched:
  // the test ran on a database of its own.
  await expect(chip(page)).toHaveAccessibleName("Branch feature/add-invoices");
  await expect(chip(page)).not.toContainText("uncommitted");
  const row = page.getByRole("row", { name: /add invoices/ });
  await expect(row).toContainText("Pending");
  await expect(row).not.toContainText("Uncommitted");
  await expect(stat(page, "Pending")).toHaveText("2");
  await expect(stat(page, "Applied")).toHaveText("0");
  expect(readFileSync(`${REPOSITORY}/dev.db`)).toEqual(database);
});

test("a change pushed without the test says so in its pull request", async ({ page }) => {
  await expect(chip(page)).toHaveAccessibleName("Branch feature/add-invoices");
  await page.getByRole("button", { name: "New change" }).click();

  // Off a main line, no branch is made by default: the change goes on the current one.
  await wizard(page).getByRole("textbox", { name: "What does this change do?" }).fill("Add payments");
  await expect(wizard(page).getByRole("checkbox", { name: "Create a branch" })).not.toBeChecked();
  await next(page).click();

  await replaceText(page, wizard(page).getByLabel("Content of V1_0_2__add_payments.sql"), "CREATE TABLE payments (id INTEGER PRIMARY KEY);");
  await replaceText(page, wizard(page).getByLabel("Content of U1_0_2__add_payments.sql"), "DROP TABLE payments;");
  await next(page).click();

  await expect(heading(page, "Test")).toBeFocused();
  await wizard(page).getByRole("button", { name: "Continue without the test" }).click();
  await expect(heading(page, "Commit")).toBeFocused();
  await wizard(page).getByRole("button", { name: "Commit 2 files" }).click();
  await next(page).click();

  // The branch follows its remote one since the first scenario: Push.
  await wizard(page).getByRole("button", { name: "Push", exact: true }).click();
  await expect(wizard(page).getByRole("textbox", { name: "Pull request description" })).toHaveValue(
    /## Scratch test\nSkipped\. CI should run the migrations before this is merged\./,
  );
  expect(commitOf(REMOTE, "refs/heads/feature/add-payments")).toBe("");
  expect(commitOf(REMOTE, "refs/heads/feature/add-invoices")).toBe(commitOf(`${REPOSITORY}/.git`, "HEAD"));
  await wizard(page).getByRole("button", { name: "Finish" }).click();
  await expect(wizard(page)).toBeHidden();
  await expect(page.getByRole("row", { name: /add payments/ })).not.toContainText("Uncommitted");
});

test("closing on the first step asks before dropping a typed description", async ({ page }) => {
  await page.getByRole("button", { name: "New change" }).click();
  await page.keyboard.press("Escape");
  await expect(wizard(page)).toBeHidden();

  await page.getByRole("button", { name: "New change" }).click();
  await wizard(page).getByRole("textbox", { name: "What does this change do?" }).fill("Add refunds");
  await page.keyboard.press("Escape");
  await expect(wizard(page).getByText("Discard what you typed?")).toBeVisible();
  await wizard(page).getByRole("button", { name: "Keep editing" }).click();
  await expect(wizard(page).getByRole("textbox", { name: "What does this change do?" })).toHaveValue("Add refunds");

  await wizard(page).getByRole("button", { name: "Close" }).click();
  await wizard(page).getByRole("button", { name: "Discard and close" }).click();
  await expect(wizard(page)).toBeHidden();
  await expect(page.getByRole("row", { name: /add refunds/ })).toHaveCount(0);
});

test("a GitHub origin gives a pull-request link for the current branch, built without contacting GitHub", async ({ page }) => {
  // Publishing comes before the link in the wizard, and this origin is never pushed to: the server is asked directly.
  const projects: { id: string; name: string }[] = await (
    await page.request.get("/api/projects", { headers: { "X-DBLift-Token": "e2e-token" } })
  ).json();
  const hub = projects.find((p) => p.name === "wizardhub");
  expect(hub).toBeDefined();
  const response = await page.request.post(`/api/projects/${hub!.id}/git/pull-request`, {
    headers: { "X-DBLift-Token": "e2e-token" },
    data: { title: "Add invoices", body: "## Change\nAdd invoices\n" },
  });
  expect(response.ok()).toBe(true);
  const link: { url: string; kind: string; branch: string } = await response.json();
  expect(link.kind).toBe("github");
  expect(link.branch).toBe("feature/add-invoices");
  expect(link.url).toBe(
    "https://github.com/example-org/example-repo/compare/feature/add-invoices?expand=1&title=Add%20invoices&body=%23%23%20Change%0AAdd%20invoices%0A",
  );
});
