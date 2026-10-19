import { expect, test, type Page } from "@playwright/test";

const EMAIL = process.env.E2E_EMAIL ?? "";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const RUN = Date.now().toString(36);
const HOSTING = `E2E hosting ${RUN}`;
const DOMAIN = `e2e-${RUN}.example.com`;
const REGISTRAR = `E2E Registrar ${RUN}`;

test.skip(!EMAIL || !PASSWORD, "Set E2E_EMAIL and E2E_PASSWORD to run end-to-end tests.");

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test.describe.serial("administrator workflow (Technical Spec §11)", () => {
  test("unauthenticated users are sent to sign in", async ({ page }) => {
    await page.goto("/domains");
    await expect(page).toHaveURL(/\/login/);
  });

  test("public overview is readable without signing in", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Domain & Hosting Overview")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Domains", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Hosting plans", exact: true })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("link", { name: "Admin sign in" })).toBeVisible();
  });

  test("add hosting, add domain, filter, change usage, check, review, email settings", async ({ page }) => {
    await signIn(page);

    // 0. Add a registrar that provides both domain names and hosting.
    await page.goto("/registrars");
    await page.getByRole("button", { name: "Add registrar" }).click();
    await page.getByRole("textbox", { name: "Name", exact: true }).fill(REGISTRAR);
    await page.getByLabel(/Hosting: can be selected/).check();
    await page.getByRole("button", { name: "Add registrar" }).last().click();
    const regRow = page.getByRole("row").filter({ hasText: REGISTRAR });
    await expect(regRow).toContainText("Domain names");
    await expect(regRow).toContainText("Hosting");

    // 1. Add a hosting account, choosing that registrar as the company.
    await page.goto("/hosting/new");
    await page.getByLabel("Account name").fill(HOSTING);
    await page.getByLabel("Hosting company").selectOption({ label: REGISTRAR });
    await page.getByLabel("Expiration date").fill("2027-01-15");
    await page.getByRole("button", { name: "Add", exact: true }).click(); // unlock admin URL
    await page.getByLabel("Admin URL (private)").fill("https://panel.e2e.test/secret");
    await page.getByRole("button", { name: "Add hosting account" }).click();
    await expect(page.getByRole("heading", { name: HOSTING })).toBeVisible();
    // The private admin URL is not displayed in the detail view.
    await expect(page.getByText("panel.e2e.test")).toHaveCount(0);

    // 2. Add a domain associated with that account.
    await page.goto("/domains/new");
    await page.getByLabel("Domain name").fill(DOMAIN.toUpperCase());
    await page.getByLabel("Hosting account").selectOption({ label: `${HOSTING} (${REGISTRAR})` });
    await page.getByLabel("Registrar", { exact: true }).selectOption({ label: REGISTRAR });
    await page.getByLabel("Expiration date").fill("2026-12-01");
    await page.getByRole("button", { name: "Add domain" }).click();
    await expect(page.getByRole("heading", { name: DOMAIN })).toBeVisible();
    await expect(page.getByRole("link", { name: HOSTING })).toBeVisible();
    await expect(page.getByText(REGISTRAR).first()).toBeVisible();

    // 3. View and filter both lists.
    await page.goto("/domains");
    await page.getByPlaceholder(/Search domains/).fill(RUN);
    await expect(page.getByRole("link", { name: DOMAIN })).toBeVisible();
    await page.getByLabel("Usage status").selectOption("inactive");
    await expect(page.getByText("No domains match these filters")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await page.goto("/hosting");
    await page.getByPlaceholder(/Search name or company/).fill(RUN);
    const row = page.getByRole("row").filter({ hasText: HOSTING });
    await expect(row).toContainText(REGISTRAR);
    await expect(row.getByRole("cell", { name: "1", exact: true })).toBeVisible(); // domain count

    // 4. Change usage status without changing expiration or registration status.
    await page.goto("/domains");
    await page.getByPlaceholder(/Search domains/).fill(RUN);
    await page.getByRole("link", { name: DOMAIN }).click();
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Usage status").selectOption("inactive");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Domain saved.")).toBeVisible();
    await expect(page.locator(".page-header").getByText("Usage: Inactive")).toBeVisible();
    await expect(page.getByText("Dec 1, 2026").first()).toBeVisible();

    // 5–6. Trigger an on-demand check and review its result in the history.
    await page.getByRole("button", { name: "Run check now" }).click();
    await expect(page.getByText(/Check finished|Check failed|still queued/)).toBeVisible({ timeout: 90_000 });
    await expect(page.locator(".timeline li").first()).toBeVisible();
    await page.getByRole("tab", { name: "Change log" }).click();
    await expect(page.getByText("Usage status: active → inactive")).toBeVisible();

    // 7. Email settings can be opened and validated (result depends on the environment).
    await page.goto("/settings/email");
    await expect(page.getByRole("heading", { name: /Amazon SES/ }).first()).toBeVisible();
    await page.getByRole("button", { name: "Validate only" }).click();
    await expect(page.getByText(/Configuration looks good|Configuration has problems/).first()).toBeVisible();

    // Clean up: archive then permanently delete; deleting the hosting must not delete the domain first.
    await page.goto("/domains");
    await page.getByPlaceholder(/Search domains/).fill(RUN);
    await page.getByRole("link", { name: DOMAIN }).click();
    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive" }).click();
    await page.getByRole("button", { name: "Delete permanently" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete permanently" }).click();
    await expect(page).toHaveURL(/\/domains$/);

    await page.goto("/hosting");
    await page.getByPlaceholder(/Search name or company/).fill(RUN);
    await page.getByRole("link", { name: HOSTING }).click();
    await page.getByRole("button", { name: "Archive" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Archive" }).click();
    await page.getByRole("button", { name: "Delete permanently" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete permanently" }).click();
    await expect(page).toHaveURL(/\/hosting$/);

    await page.goto("/registrars");
    const cleanupRow = page.getByRole("row").filter({ hasText: REGISTRAR });
    await cleanupRow.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
    await expect(page.getByRole("row").filter({ hasText: REGISTRAR })).toHaveCount(0);
  });

  test("dashboard is usable on a phone @mobile", async ({ page }) => {
    await signIn(page);
    await expect(page.getByRole("button", { name: "Menu" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await page.getByRole("button", { name: "Menu" }).click();
    await page.locator("#sidebar").getByRole("link", { name: "Domains", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Domains", level: 1 })).toBeVisible();
  });
});
