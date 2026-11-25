import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("Metrics page", () => {
  test("shows the seeded leads in four sentences, with tables behind each chart", async ({ page }) => {
    await page.goto("/dashboard/metrics");
    await expect(page.getByRole("heading", { level: 1, name: "How is it going?" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Metrics" }).first()).toHaveAttribute("aria-current", "page");

    const status = page.locator("#m-status");
    await expect(status).toContainText(/\d+ leads came in/);
    await expect(page.getByRole("img", { name: /came in/ })).toBeVisible();
    await expect(page.locator("#m-score")).toContainText(/scored leads are (hot|warm|cold)/);
    await expect(page.locator("section.mc:has(#m-score) .legend")).toContainText("Hot, 75 and above");
    await expect(page.locator("#m-day")).toContainText(/\d+ leads? in \d+ days/);
    await expect(page.locator("#m-time")).toContainText(/qualified within|No lead has been qualified/);
    await expect(page.locator("#m-cost")).toContainText(/No model calls|fake provider|Each lead costs/);

    // The chart really renders bars (recharts draws SVG rectangles).
    await expect(page.locator("section.mc:has(#m-score) path.recharts-rectangle").first()).toBeVisible();

    // The data table fallback carries the same numbers.
    const section = page.locator("section.mc").filter({ has: page.locator("#m-status") });
    await section.getByText("View as a table").click();
    const row = section.getByRole("row", { name: /^Sent/ });
    await expect(row).toBeVisible();
    expect(await row.getByRole("cell").innerText()).toMatch(/^\d+$/);
  });

  test("changing the period reloads the figures and says so", async ({ page }) => {
    await page.goto("/dashboard/metrics");
    await expect(page.getByText("Last 30 days")).toBeVisible();
    await page.getByRole("button", { name: "7 days" }).click();
    await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Last 7 days")).toBeVisible();
    const days = page.locator("section.mc").filter({ has: page.locator("#m-day") });
    await days.getByText("View as a table").click();
    await expect(days.getByRole("row").nth(1)).toBeVisible(); // only days with leads
    await days.getByRole("button", { name: "Show all days" }).click();
    await expect(days.getByRole("row")).toHaveCount(8); // header + 7 days
  });

  for (const [label, viewport] of [
    ["desktop", { width: 1280, height: 900 }],
    ["mobile", { width: 390, height: 844 }],
  ] as const) {
    test(`has no serious accessibility violations on ${label}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/dashboard/metrics");
      await expect(page.locator("section.mc:has(#m-score) path.recharts-rectangle").first()).toBeVisible();
      await page.locator("section.mc summary").first().click();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
      expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
    });
  }

  test("an empty period explains itself", async ({ page }) => {
    await page.route("**/bff/metrics*", async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      await route.fulfill({ response: res, json: { ...body, total_leads: 0 } });
    });
    await page.goto("/dashboard/metrics");
    await expect(page.getByRole("heading", { name: "No leads in this period" })).toBeVisible();
  });
});
