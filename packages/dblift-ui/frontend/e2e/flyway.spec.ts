import { expect, test } from "@playwright/test";

import { FIXTURES } from "./paths";

test("convert a Flyway project, preview and import its history", async ({ page }) => {
  await page.goto("/?token=e2e-token");
  await page.getByRole("button", { name: "Add project", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add project" });
  await add.getByLabel("Folder path").fill(`${FIXTURES}/flywayapp`);
  await add.getByRole("button", { name: "Look for configs" }).click();
  await add.getByRole("button", { name: "Convert flyway.conf" }).click();

  const form = page.getByRole("dialog", { name: "New configuration" });
  await expect(form.getByRole("radio", { name: "SQLite" })).toBeChecked();
  await expect(form.getByLabel("Database file")).toHaveValue("./legacy.db");
  await expect(form.getByLabel("Migrations folder")).toHaveValue("./sql");
  await expect(form.getByLabel("Project name")).toHaveValue("flywayapp");
  await expect(page.getByText("hunter2")).toHaveCount(0);
  await form.getByRole("button", { name: "Create" }).click();
  await expect(form).toBeHidden();

  await expect(page.getByRole("heading", { name: "flywayapp" })).toBeVisible();
  const banner = page.getByRole("region", { name: "Flyway history" });
  await expect(banner).toContainText("flyway_schema_history");
  await expect(page.getByRole("row", { name: /create c/ })).toContainText("Pending");

  await banner.getByRole("button", { name: "Preview the import" }).click();
  await expect(banner.getByRole("status")).toHaveText("2 entries would be imported from flyway_schema_history");
  await expect(page.getByRole("row", { name: /create a/ })).toContainText("Pending");

  await banner.getByRole("button", { name: "Import history" }).click();
  await banner.getByRole("button", { name: "Import", exact: true }).click();

  await expect(banner).toBeHidden();
  await expect(page.getByRole("row", { name: /create a/ })).not.toContainText("Pending");
  await expect(page.getByRole("row", { name: /create b/ })).not.toContainText("Pending");
  await expect(page.getByRole("row", { name: /create c/ })).toContainText("Pending");
  await expect(page.getByText("2 entries imported from flyway_schema_history")).toBeVisible();
});
