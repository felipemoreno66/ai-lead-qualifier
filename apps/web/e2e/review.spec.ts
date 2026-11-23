import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { applicant, applyAndOpen, mailText, mailsTo, waitForDraft } from "./helpers";

const WCAG = ["wcag2a", "wcag2aa", "wcag21aa"];

test.describe("Phase 2: review the drafted reply", () => {
  test("apply, qualify, edit and approve: the email reaches Mailpit", async ({ page, request }) => {
    const who = applicant("Ana");
    await applyAndOpen(page, who);
    await waitForDraft(page, who.first);

    // The qualification card explains the score criterion by criterion.
    await expect(page.getByRole("heading", { name: "Why this score" })).toBeVisible();
    await expect(page.getByText("Goal fit")).toBeVisible();
    await expect(page.getByLabel(/points$/).first()).toBeVisible();
    await expect(page.getByLabel(/^Score \d+ out of 100$/)).toBeVisible();

    // Nothing is sent before approval.
    expect(await mailsTo(request, who.email)).toHaveLength(0);

    await page.getByRole("button", { name: "Edit" }).click();
    const body = page.getByLabel("Message");
    await expect(body).toBeEditable();
    await body.fill(`${await body.inputValue()}\n\nP.S. Evening cohorts are available.`);
    await page.getByRole("button", { name: "Approve and send edits" }).click();

    await expect(page.getByRole("status").filter({ hasText: "Approved with your edits" })).toBeVisible();
    await expect(page.locator(".letter .badge")).toContainText(/Sent|Approved, sending/);
    await expect(page.locator(".letter .badge")).toContainText("Sent", { timeout: 30_000 });
    await expect(page.getByText("Edited by you before sending")).toBeVisible();
    await expect(page.getByText("The reply draft was edited and approved.")).toBeVisible();

    await expect.poll(async () => (await mailsTo(request, who.email)).length, { timeout: 30_000 }).toBe(1);
    const [mail] = await mailsTo(request, who.email);
    expect(mail.Subject).toContain("Northwind");
    expect(await mailText(request, mail.ID)).toContain("P.S. Evening cohorts are available.");

    // The agent run log lists the model calls.
    await page.getByText("Agent run log").click();
    const log = page.locator("#runlog table").first();
    await expect(log.getByRole("rowheader", { name: "extract" })).toBeVisible();
    await expect(log.getByRole("rowheader", { name: "qualify" })).toBeVisible();
    await expect(log.getByRole("rowheader", { name: "draft" })).toBeVisible();
    await expect(log).toContainText("fake");
  });

  test("approving without edits sends the draft as written", async ({ page, request }) => {
    const who = applicant("Beto");
    await applyAndOpen(page, who);
    await waitForDraft(page, who.first);
    await expect(page.getByLabel("Message")).not.toBeEditable();
    await page.getByRole("button", { name: "Approve and send", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Approved. The email is being sent." })).toBeVisible();
    await expect(page.locator(".letter .badge")).toContainText("Sent", { timeout: 30_000 });
    await expect(page.getByText("Edited by you before sending")).toHaveCount(0);
    await expect.poll(async () => (await mailsTo(request, who.email)).length, { timeout: 30_000 }).toBe(1);
  });

  test("rejecting closes the lead and sends nothing", async ({ page, request }) => {
    const who = applicant("Carla");
    await applyAndOpen(page, who);
    await waitForDraft(page, who.first);
    await page.getByRole("button", { name: "Reject" }).click();
    await page.getByLabel("Note (optional)").fill("Not a fit this term.");
    await page.getByRole("button", { name: "Reject draft" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Rejected. Nothing was sent" })).toBeVisible();
    await expect(page.locator("header.dh .badge")).toContainText("Rejected");
    await expect(page.getByRole("heading", { name: `Draft reply to ${who.first}` })).toHaveCount(0);
    await expect(page.getByText("note: Not a fit this term.")).toBeAttached();
    expect(await mailsTo(request, who.email)).toHaveLength(0);
  });

  test("regenerating writes a new version and keeps the old one", async ({ page }) => {
    const who = applicant("Diego");
    await applyAndOpen(page, who);
    await waitForDraft(page, who.first);
    await page.getByRole("button", { name: "Regenerate" }).click();
    await page.getByLabel("What should change? (optional)").fill("Shorter, please.");
    await page.getByRole("button", { name: "Write a new draft" }).click();
    await expect(page.getByRole("status").filter({ hasText: "A new draft is ready" })).toBeVisible();
    await expect(page.locator(".draft-meta")).toContainText("2 ·");
    await page.getByText("Earlier drafts").click();
    await expect(page.locator("#earlier")).toContainText("Version 1");
    await expect(page.locator("#earlier")).toContainText("note: Shorter, please.");
  });

  test("a draft that fails the checks needs an explicit Send anyway", async ({ page, request }) => {
    const who = applicant("Elena");
    await applyAndOpen(page, who);
    await waitForDraft(page, who.first);
    await page.getByRole("button", { name: "Edit" }).click();
    const body = page.getByLabel("Message");
    await body.fill(`${await body.inputValue()}\n\nPay the deposit at https://evil.example/pay today.`);
    await page.getByRole("button", { name: "Approve and send edits" }).click();

    const alert = page.getByRole("alert").filter({ hasText: "did not pass the safety checks" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("evil.example");
    expect(await mailsTo(request, who.email)).toHaveLength(0);
    // The failed attempt did not change anything: the draft is still waiting.
    await expect(page.getByRole("heading", { name: `Draft reply to ${who.first}` })).toBeVisible();

    const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
    const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
    expect(serious.map((v) => `${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);

    await alert.getByRole("button", { name: "Send anyway" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Approved with your edits" })).toBeVisible();
    await expect(page.getByText("The reply draft was edited and approved despite failed checks.")).toBeVisible();
    await expect(page.locator(".letter .badge")).toContainText("Sent", { timeout: 30_000 });
    await expect.poll(async () => (await mailsTo(request, who.email)).length, { timeout: 30_000 }).toBe(1);
  });
});

test.describe("accessibility of the review UI (axe)", () => {
  for (const [label, viewport] of [
    ["desktop", { width: 1280, height: 900 }],
    ["mobile", { width: 390, height: 844 }],
  ] as const) {
    test(`pending draft, editing and sent letter on ${label}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      const who = applicant(label === "desktop" ? "Fabio" : "Gina");
      await applyAndOpen(page, who);
      await waitForDraft(page, who.first);
      const check = async (state: string) => {
        const results = await new AxeBuilder({ page }).withTags(WCAG).analyze();
        const serious = results.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
        expect(serious.map((v) => `${state} ${v.id}: ${v.nodes[0]?.html}`)).toEqual([]);
      };
      await check("pending");
      await page.getByRole("button", { name: "Regenerate" }).click();
      await check("regenerate panel");
      await page.getByRole("button", { name: "Edit" }).click();
      await check("editing");
      await page.getByRole("button", { name: "Approve and send" }).click();
      await expect(page.locator(".letter .badge")).toContainText("Sent", { timeout: 30_000 });
      await page.getByText("Agent run log").click();
      await check("sent");
      // Touch targets: every action button is at least 44px tall.
      for (const button of await page.locator("main button.btn").all()) {
        const box = await button.boundingBox();
        if (box) expect(box.height).toBeGreaterThanOrEqual(44);
      }
    });
  }
});
