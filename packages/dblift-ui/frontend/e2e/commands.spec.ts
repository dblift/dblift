import { expect, test } from "@playwright/test";

const stat = (page: import("@playwright/test").Page, name: string) =>
  page.locator("dl.summary__stats div", { has: page.locator("dt", { hasText: name }) }).locator("dd");

test.beforeEach(async ({ page }) => {
  await page.goto("/?token=e2e-token");
  await expect(page).toHaveURL(/\/$/);
});

test("preview, apply, then undo the last migration", async ({ page }) => {
  await page.getByRole("button", { name: /^shop/ }).click();
  await expect(stat(page, "Pending")).toHaveText("2");

  await page.getByRole("button", { name: "Migrate" }).click();
  const preview = page.getByRole("region", { name: "SQL to be applied" });
  await expect(preview.getByText("CREATE TABLE customers (id INTEGER PRIMARY KEY);")).toBeVisible();
  await preview.getByRole("button", { name: "Apply 2 migrations" }).click();

  await expect(page.getByRole("log").getByText("✓ done")).toBeVisible();
  await expect(stat(page, "Applied")).toHaveText("2");
  await expect(stat(page, "Version")).toHaveText("1.0.1");
  await expect(page.getByRole("button", { name: "Migrate" })).toBeDisabled();

  await page.getByRole("button", { name: "Undo last migration" }).click();
  await page.getByRole("button", { name: "Confirm undo" }).click();

  await expect(page.getByRole("log").getByText("Reverted with U1_0_1__create_orders.sql")).toBeVisible();
  await expect(stat(page, "Applied")).toHaveText("1");
  await expect(stat(page, "Pending")).toHaveText("1");
});

test("a failing migration is reported, then repaired", async ({ page }) => {
  await page.getByRole("button", { name: /^broken/ }).click();
  await page.getByRole("button", { name: "Migrate" }).click();
  await page.getByRole("button", { name: "Apply 2 migrations" }).click();

  await expect(page.getByRole("log").getByText(/Failed V1_0_1__typo\.sql/)).toBeVisible();
  await expect(stat(page, "Failed")).toHaveText("1");
  await expect(stat(page, "Applied")).toHaveText("1");
  await expect(page.getByRole("button", { name: "Migrate" })).toBeDisabled();

  await page.getByRole("button", { name: "Repair" }).click();
  await page.getByRole("button", { name: "Confirm repair" }).click();

  await expect(page.getByRole("log").getByText("History repaired")).toBeVisible();
  await expect(page.getByRole("button", { name: "Repair" })).toHaveCount(0);
  await expect(stat(page, "Pending")).toHaveText("1");
});

test("the interface talks only to its own server", async ({ page }) => {
  const hosts = new Set<string>();
  page.on("request", (request) => hosts.add(new URL(request.url()).host));

  await page.reload();
  await page.getByRole("button", { name: /^shop/ }).click();
  await expect(page.getByRole("table", { name: "Migrations" })).toBeVisible();

  expect([...hosts]).toEqual(["127.0.0.1:8799"]);
});
