import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SLUG = "northwind-academy";
const stamp = Date.now().toString(36);
const NAME = `Eve Playwright ${stamp}`;
const EMAIL = `eve.${stamp}@example.com`;

async function fillApplication(page: Page, name: string, email: string) {
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Country").selectOption("CO");
  await page.getByRole("radio", { name: "Data & AI Course" }).check();
  await page.getByLabel("Career goal").fill("Move from accounting into data work.");
  await page.getByRole("radio", { name: "USD 500–2,500" }).check();
  await page.getByRole("radio", { name: "5–10 h" }).check();
  await page.getByLabel("What are you looking for?").fill("Is there a payment plan?");
}

test.describe("Phase 1: apply and see the lead in the dashboard", () => {
  test("apply, then find the lead, filter, open it and delete it", async ({ page }) => {
    await page.goto(`/w/${SLUG}/apply`);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Northwind Academy");
    await fillApplication(page, NAME, EMAIL);
    await page.getByLabel(/I have read the privacy notice/).check();
    await page.waitForTimeout(2200); // the server treats sub-2-second submissions as bots
    await page.getByRole("button", { name: "Apply" }).click();

    await expect(page).toHaveURL(/\/apply\/thanks\?ref=NW-/);
    await expect(page.getByRole("heading", { name: "Application received" })).toBeVisible();
    const reference = (await page.locator(".refrow b").innerText()).trim();
    expect(reference).toMatch(/^NW-[A-Z0-9]{6}$/);

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Who should you reply to first?" })).toBeVisible();
    await page.getByRole("button", { name: "New", exact: true }).click();
    await expect(page).toHaveURL(/status=new/);
    await page.getByLabel("Search by name or email").fill(EMAIL);
    await expect(page).toHaveURL(/q=eve/);
    const row = page.getByRole("link", { name: NAME });
    await expect(row).toBeVisible();
    await expect(page.getByRole("heading", { name: "Not scored yet" })).toBeVisible();

    await row.click();
    await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
    await expect(page.getByText(`ref ${reference}`)).toBeVisible();
    await expect(page.getByText("Application received (reference " + reference + ")")).toBeVisible();
    // The dispatcher hands the event over within a few seconds.
    await expect
      .poll(
        async () => {
          await page.reload();
          return page.getByText(/event was delivered to the orchestrator|n8n confirmed/).count();
        },
        { timeout: 30_000, intervals: [1000, 2000, 3000] },
      )
      .toBeGreaterThan(0);
    await expect(page.getByText("Delivered at")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Why this score" })).toHaveCount(0);

    await page.getByRole("button", { name: "Delete this lead" }).click();
    await page.getByRole("button", { name: "Delete permanently" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await page.getByLabel("Search by name or email").fill(EMAIL);
    await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
  });

  test("score and status filters work on the seeded leads", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Hot" })).toBeVisible();
    await page.locator("#score").selectOption("hot");
    await expect(page).toHaveURL(/score=hot/);
    await expect(page.getByRole("link", { name: "Mateo Alvarez" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Amara Okafor" })).toHaveCount(0);
    await page.getByRole("button", { name: "Error", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByRole("link", { name: "Priya Nair" })).toBeVisible();
  });

  test("a failed lead shows its reason and can be re-queued", async ({ page }) => {
    await page.goto("/dashboard?status=error");
    await page.getByRole("link", { name: "Priya Nair" }).click();
    await expect(page.getByText("llm_timeout")).toBeVisible();
    await page.getByRole("button", { name: "Re-trigger" }).first().click();
    await expect(page.getByText("Queued again", { exact: false }).first()).toBeVisible();
  });

  test("the form explains mistakes instead of failing silently", async ({ page }) => {
    await page.goto(`/w/${SLUG}/apply`);
    await page.getByRole("button", { name: "Apply" }).click();
    await expect(page.locator(".form-alert")).toContainText("Please check these fields");
    await expect(page.getByText("This field is required.").first()).toBeVisible();
  });

  test("the form switches to Spanish", async ({ page }) => {
    await page.goto(`/w/${SLUG}/apply`);
    await page.getByRole("button", { name: "ES" }).click();
    await expect(page.getByLabel("Nombre completo")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar solicitud" })).toBeVisible();
  });

  test("draft and unknown workspaces have no public form", async ({ page }) => {
    for (const slug of ["david-moreno", "does-not-exist"]) {
      const response = await page.goto(`/w/${slug}/apply`);
      expect(response?.status()).toBe(404);
    }
  });
});

test.describe("accessibility smoke (axe)", () => {
  for (const [name, path] of [
    ["public form", `/w/${SLUG}/apply`],
    ["thank-you page", `/w/${SLUG}/apply/thanks?ref=NW-ABC234`],
    ["privacy notice", `/privacy/${SLUG}`],
    ["leads list", "/dashboard"],
  ] as const) {
    test(`${name} has no serious violations`, async ({ page }) => {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
    });
  }

  test("lead detail has no serious violations", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("link", { name: "Mateo Alvarez" }).click();
    await expect(page.getByRole("heading", { name: "Why this score" })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
  });
});
