import { expect, test } from "@playwright/test";

import { FIXTURES } from "./paths";

// The scenarios run in file order on one server: the later ones start from the projects
// the first one added.

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
});

test("open a folder, pick among the configs found, add them", async ({ page }) => {
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add project" });
  await dialog.getByLabel("Folder path").fill(`${FIXTURES}/monorepo`);
  await dialog.getByRole("button", { name: "Look for configs" }).click();

  await expect(dialog.getByRole("checkbox", { name: "dblift.yaml", exact: true })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: "services/billing/dblift.yaml" })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: "dblift.yaml.template" })).not.toBeChecked();
  await expect(dialog.getByText("legacy/flyway.conf")).toBeVisible();
  await expect(dialog.getByText("legacy/sql", { exact: true })).toBeVisible();
  await expect(dialog.getByText("main", { exact: true })).toBeVisible();

  await dialog.getByRole("button", { name: "Add 2 projects" }).click();
  await expect(dialog).toBeHidden();

  const group = page.getByRole("group", { name: "monorepo" });
  await expect(group.getByRole("button", { name: /^monorepo · dblift/ })).toBeVisible();
  await expect(group.getByRole("button", { name: /^monorepo · services\/billing/ })).toBeVisible();
  await group.getByRole("button", { name: /^monorepo · services\/billing/ }).click();
  await expect(page.getByRole("row", { name: /create invoices/ })).toBeVisible();
});

test("on a narrow screen, a repository's projects scroll with the rest of the list", async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  const nested = page.getByRole("group", { name: "monorepo" }).getByRole("list");
  await expect(nested.getByRole("listitem")).toHaveCount(2);

  // Only the sidebar's own strip scrolls; the group does not get a scrollbar of its own.
  const widths = await nested.evaluate((list) => [list.scrollWidth, list.clientWidth]);
  expect(widths[0]).toBe(widths[1]);
});

test("a second scan shows what is already added", async ({ page }) => {
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add project" });
  await dialog.getByRole("group", { name: "Scan again" }).getByRole("button", { name: `${FIXTURES}/monorepo` }).click();

  await expect(dialog.getByRole("checkbox", { name: "dblift.yaml", exact: true })).toBeDisabled();
  await expect(dialog.getByText("already added").first()).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Add 0 projects" })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
});

test("clone a repository, then add what it holds", async ({ page }) => {
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add project" });
  await dialog.getByRole("radio", { name: "Clone a repository" }).check();
  await dialog.getByLabel("Repository address").fill(`${FIXTURES}/monorepo.git`);
  await dialog.getByLabel("Clone into").fill(`${FIXTURES}/clones`);
  await dialog.getByRole("button", { name: "Clone and look for configs" }).click();

  await expect(dialog.getByText(`${FIXTURES}/clones/monorepo`)).toBeVisible();
  await dialog.getByRole("checkbox", { name: "services/billing/dblift.yaml" }).uncheck();
  await expect(dialog.getByLabel("Name for dblift.yaml")).toHaveValue("monorepo");
  await dialog.getByLabel("Name for dblift.yaml").fill("monorepo (clone)");
  await dialog.getByRole("button", { name: "Add 1 project" }).click();

  await expect(page.getByRole("heading", { name: "monorepo (clone)" })).toBeVisible();
  await expect(page.getByRole("row", { name: /create accounts/ })).toBeVisible();
});

test("a refused address is explained", async ({ page }) => {
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Add project" });
  await dialog.getByRole("radio", { name: "Clone a repository" }).check();
  await dialog.getByLabel("Repository address").fill("ext::sh -c id");
  await dialog.getByLabel("Clone into").fill(`${FIXTURES}/clones`);
  await dialog.getByRole("button", { name: "Clone and look for configs" }).click();

  await expect(dialog.getByRole("alert")).toContainText("not a repository address");
});
