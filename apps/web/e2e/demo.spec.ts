import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// First-start demo: `docker compose up` seeds Northwind, drafts, run logs and Ask answers with the
// fake provider. These run first (alphabetical order) and only read the seeded state.
test.describe("Keyless demo on first open", () => {
  test("says plainly that replies come from a stand-in", async ({ page }) => {
    await page.goto("/dashboard");
    const bar = page.getByRole("note").filter({ hasText: "Demo mode" });
    await expect(bar).toContainText("no real AI calls");
  });

  test("a pending lead already has a draft, a score explanation and a run log", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("link", { name: "Mateo Alvarez" }).click();
    await expect(page.getByRole("heading", { name: "Draft reply to Mateo" })).toBeVisible();
    await expect(page.getByLabel("Message")).toHaveValue(/Full Stack Bootcamp/);
    await expect(page.getByRole("heading", { name: "Why this score" })).toBeVisible();
    await expect(page.getByText("Their goal, in short")).toBeVisible();
    await page.getByText("Agent run log").click();
    const log = page.locator("#runlog table").first();
    await expect(log.getByRole("rowheader", { name: "extract" })).toBeVisible();
    await expect(log).toContainText("fake");
  });

  test("sent, rejected and failed leads each tell their story (read-only, any order)", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("link", { name: "Lucas Ferreira" }).click();
    await expect(page.locator(".letter .badge")).toContainText("Sent");
    await expect(page.getByText("Edited by you before sending")).toBeVisible();
    await page.goto("/dashboard");
    await page.getByRole("link", { name: "Elena Petrova" }).click();
    await expect(page.getByText("Not worth a personal reply.")).toBeAttached();
    await page.goto("/dashboard?q=priya");
    await page.getByRole("link", { name: "Priya Nair" }).click();
    await page.getByText("Agent run log").click();
    await expect(page.locator("#runlog")).toContainText("qualify failed: llm_timeout");
  });

  test("metrics and Ask have content, and the fake provider is called out", async ({ page }) => {
    await page.goto("/dashboard/metrics");
    await expect(page.locator("#m-cost")).toContainText("fake provider is free");
    await expect(page.locator("#m-time")).toContainText("qualified within");
    await page.goto("/dashboard/ask");
    await expect(page.getByRole("region", { name: "Recent questions" })).toContainText("Data & AI Course");
  });

  test("the demo notice does not break accessibility", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("note").filter({ hasText: "Demo mode" })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
  });
});
