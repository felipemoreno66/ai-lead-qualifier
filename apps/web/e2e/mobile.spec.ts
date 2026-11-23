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
