import AxeBuilder from "@axe-core/playwright";
import { expect, request, test, type Page } from "@playwright/test";
import { SLUG } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21aa"];
const AGENT = process.env.E2E_AGENT_URL ?? "http://127.0.0.1:8000";
const ADMIN_TOKEN = process.env.E2E_ADMIN_TOKEN ?? "local-dev-admin-token-change-me";

// The stack runs with fake embeddings and the fake provider (docker-compose.ci.yml), so the
// knowledge base is ingested here, offline, before the first question.
test.beforeAll(async () => {
  const api = await request.newContext({ baseURL: AGENT });
  const res = await api.post(`/admin/kb/${SLUG}/reindex`, {
    headers: { Authorization: `Bearer ${ADMIN_TOKEN}` },
  });
  expect(res.ok()).toBe(true);
  await api.dispose();
});

async function ask(page: Page, question: string) {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
}

test.describe("Phase 3: ask the docs", () => {
  test("a covered question shows the answer and sources with their quotes", async ({ page }) => {
    await page.goto("/dashboard/ask");
    await expect(page.getByRole("heading", { level: 1, name: "Ask the docs" })).toBeVisible();
    // Unique per run: the log persists, so a repeated question would match older entries too.
    const question = `How much does the Data & AI Course cost? (ref ${Date.now()})`;
    await ask(page, question);

    const answer = page.locator(".thread .msg.a").first();
    await expect(answer).toBeVisible({ timeout: 30_000 });
    await expect(answer).not.toContainText("Not in the docs");
    // Focus returns to the input once the answer has landed (before the sources are touched).
    await expect(page.getByLabel("Your question")).toBeFocused();
    const sources = answer.getByRole("list", { name: "Sources" });
    await expect(sources.locator("summary").first()).toBeVisible();
    const first = sources.locator("details").first();
    await expect(first.locator(".cq")).toBeHidden();
    await first.locator("summary").click();
    await expect(first.locator(".cq")).toContainText("“");

    // The question is logged and listed after a reload.
    await page.reload();
    await expect(
      page.getByRole("region", { name: "Recent questions" }).getByText(question),
    ).toBeVisible();
  });

  test("a question the documents do not cover says so and shows no sources", async ({ page }) => {
    await page.goto("/dashboard/ask");
    await ask(page, "zxqv wxyz plugh");
    const answer = page.locator(".thread .msg.nodoc");
    await expect(answer).toBeVisible({ timeout: 30_000 });
    await expect(answer).toContainText("Not in the docs");
    await expect(answer).toContainText("Not covered in our documentation");
    await expect(answer.getByRole("list", { name: "Sources" })).toHaveCount(0);
  });

  test("the Ask button needs a real question", async ({ page }) => {
    await page.goto("/dashboard/ask");
    await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
    await page.getByLabel("Your question").fill("hi");
    await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
    await page.getByLabel("Your question").fill("What is the refund policy?");
    await expect(page.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  test("the page has no accessibility violations with answers on screen", async ({ page }) => {
    await page.goto("/dashboard/ask");
    await ask(page, "How much does the Data & AI Course cost?");
    await expect(page.locator(".thread .msg.a").first()).toBeVisible({ timeout: 30_000 });
    await ask(page, "zxqv wxyz plugh");
    await expect(page.locator(".thread .msg.nodoc")).toBeVisible({ timeout: 30_000 });
    await page.locator(".cite-d summary").first().click();
    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    expect(results.violations).toEqual([]);
  });

  test.describe("mobile", () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test("no horizontal overflow at 390px, with the form above the tab bar", async ({ page }) => {
      await page.goto("/dashboard/ask");
      await ask(page, "How much does the Data & AI Course cost?");
      await expect(page.locator(".thread .msg.a").first()).toBeVisible({ timeout: 30_000 });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      const form = await page.locator("form.ask").boundingBox();
      const tabs = await page.locator("nav.tabs").boundingBox();
      expect(form && tabs && form.y + form.height <= tabs.y + 1).toBe(true);
    });
  });
});
