import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Runs only against a stack started with the operator login (ADMIN_* set); CI starts one after the
// main suite. Locally: E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD plus E2E_BASE_URL of that stack.
const EMAIL = process.env.E2E_ADMIN_EMAIL;
const PASSWORD = process.env.E2E_ADMIN_PASSWORD;
test.skip(!EMAIL || !PASSWORD, "operator login not configured for this run");

test("the dashboard is closed without a session and sends you to the login", async ({ page, request }) => {
  await page.goto("/dashboard/metrics");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard%2Fmetrics$/);
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  expect((await request.get("/bff/leads")).status()).toBe(401);
  expect((await request.get("/api/auth/get-session")).status()).toBe(404);
});

test("the public pages stay open", async ({ page }) => {
  const res = await page.goto("/");
  expect(res?.status()).toBe(200);
  await expect(page).toHaveURL(/\/$/);
});

test("a wrong password shows one generic message and stays on the login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL!);
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("email or password is not right");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill("someone-else@example.com");
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("email or password is not right");
});

test("sign in, use the dashboard, sign out", async ({ page, context }) => {
  await page.goto("/dashboard/metrics");
  await page.getByLabel("Email").fill(EMAIL!);
  await page.getByLabel("Password").fill(PASSWORD!);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard\/metrics$/);
  const session = (await context.cookies()).find((c) => /session_token/.test(c.name));
  expect(session).toMatchObject({ httpOnly: true, sameSite: "Lax" });
  expect((await page.request.get("/bff/workspaces")).status()).toBe(200);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=/);
  expect((await page.request.get("/bff/workspaces")).status()).toBe(401);
});

test("the login page has no accessibility violations and does not overflow at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
