import { expect, test } from "@playwright/test";

const SLUG = "northwind-academy";

test.use({ viewport: { width: 390, height: 844 } });

for (const path of [
  `/w/${SLUG}/apply`,
  `/privacy/${SLUG}`,
  "/dashboard",
  "/dashboard?status=bogus&page=999&minScore=abc",
  "/dashboard/leads/00000000-0000-0000-0000-000000000000",
]) {
  test(`no horizontal overflow at 390px: ${path}`, async ({ page }) => {
    await page.goto(path);
    await expect(page.locator("main, body").first()).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
}

test("unknown lead id shows a friendly not-found state", async ({ page }) => {
  await page.goto("/dashboard/leads/00000000-0000-0000-0000-000000000000");
  await expect(page.getByText("Lead not found")).toBeVisible();
});

test.describe("mobile list layout", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("status chips are fully visible and the tab bar never covers the last lead", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Who should you reply to first?" })).toBeVisible();
    for (const name of ["All", "New", "Error"]) {
      const box = await page.getByRole("button", { name, exact: true }).boundingBox();
      expect(box && box.x >= 0 && box.x + box.width <= 390).toBe(true);
    }
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const lastRow = page.locator("table.leads tbody tr").last();
    const tabs = page.locator("nav.tabs");
    const row = await lastRow.boundingBox();
    const bar = await tabs.boundingBox();
    expect(row && bar && row.y + row.height <= bar.y).toBe(true);
  });
});
