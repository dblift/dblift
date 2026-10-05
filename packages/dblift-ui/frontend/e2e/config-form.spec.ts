import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { FIXTURES } from "./paths";

// The scenarios run in file order on one server: the later ones edit the project the first one created.

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
});

test("create a configuration for a folder that has migrations and no config, then migrate", async ({ page }) => {
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add project" });
  await add.getByLabel("Folder path").fill(`${FIXTURES}/bare`);
  await add.getByRole("button", { name: "Look for configs" }).click();
  await expect(add.getByText("No config file was found in this folder.")).toBeVisible();
  await add.getByRole("button", { name: "Create configuration", exact: true }).click();

  const form = page.getByRole("dialog", { name: "New configuration" });
  await expect(add).toBeHidden();
  await expect(form.getByLabel("Migrations folder")).toHaveValue("./sql");
  await form.getByRole("radio", { name: "SQLite" }).check();
  await form.getByLabel("Database file").fill("./bare.db");
  await expect(form.getByText("type: sqlite")).toBeVisible();
  await expect(form.getByText("path: ./bare.db")).toBeVisible();
  await form.getByRole("button", { name: "Create" }).click();

  await expect(form).toBeHidden();
  await expect(page.getByRole("heading", { name: "bare" })).toBeVisible();
  await expect(page.getByRole("row", { name: /create things/ })).toBeVisible();
  expect(readFileSync(`${FIXTURES}/bare/dblift.yaml`, "utf8")).toContain("directory: ./sql");
});

test("edit the configuration: add an environment, see it in the header", async ({ page }) => {
  await page.getByRole("button", { name: /^bare/ }).click();
  await page.getByRole("button", { name: "Configuration" }).click();
  const form = page.getByRole("dialog", { name: "Configuration of bare" });
  await expect(form.getByLabel("Database file")).toHaveValue("./bare.db");

  await form.getByRole("button", { name: "Add environment" }).click();
  const block = form.getByRole("group", { name: "Environment 1" });
  await block.getByLabel("Name").fill("staging");
  await block.getByLabel("Database file").fill("./staging.db");
  await expect(form.getByText("staging:")).toBeVisible();
  await form.getByRole("button", { name: "Save" }).click();

  await expect(form).toBeHidden();
  await expect(page.getByRole("tab", { name: "staging" })).toBeVisible();
});

test("a problem from the loader blocks saving", async ({ page }) => {
  await page.getByRole("button", { name: /^bare/ }).click();
  await page.getByRole("button", { name: "Configuration" }).click();
  const form = page.getByRole("dialog", { name: "Configuration of bare" });

  await form.getByRole("radio", { name: "PostgreSQL" }).check();
  // The staging environment added above has the same fields: these are the main connection's.
  const main = form.getByRole("group", { name: "Connection" });
  await main.getByLabel("Host").fill("db.example.com");
  await main.getByLabel("Database", { exact: true }).fill("shop");
  // The loader also needs a user for PostgreSQL; with one, the empty password is the problem left.
  await main.getByLabel("User").fill("app");
  await main.getByRole("radio", { name: "Type it here" }).check();
  await expect(form.getByText(/written in the file in clear text/)).toBeVisible();
  await expect(form.getByRole("alert")).toBeVisible();
  await expect(form.getByRole("button", { name: "Save" })).toBeDisabled();

  await main.getByLabel("Password value").fill("s3cret");
  await expect(form.getByRole("alert")).toBeHidden();
  await expect(form.getByText("s3cret")).toBeHidden();
  await expect(form.getByText("password: '********'").or(form.getByText('password: "********"')).or(form.getByText("password: ********"))).toBeVisible();
  await form.getByRole("button", { name: "Close" }).click();
});
