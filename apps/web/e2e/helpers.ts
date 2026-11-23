import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const SLUG = "northwind-academy";
export const MAILPIT = process.env.MAILPIT_URL ?? "http://127.0.0.1:8025";

let counter = 0;
/** A unique fake applicant so tests never see each other's leads. */
export function applicant(label: string) {
  counter += 1;
  const stamp = `${Date.now().toString(36)}${counter}`;
  return { first: label, name: `${label} Reviewer ${stamp}`, email: `${label.toLowerCase()}.${stamp}@example.com` };
}

/** Fill and submit the public form, then open the lead in the dashboard. */
export async function applyAndOpen(page: Page, who: { name: string; email: string }): Promise<void> {
  await page.goto(`/w/${SLUG}/apply`);
  await page.getByLabel("Full name").fill(who.name);
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Country").selectOption("CO");
  await page.getByRole("radio", { name: "Full Stack Bootcamp" }).check();
  await page.getByLabel("Career goal").fill("I want to become a junior full stack developer within a year.");
  await page.getByRole("radio", { name: "USD 2,500–5,000" }).check();
  await page.getByRole("radio", { name: "10–20 h" }).check();
  await page.getByLabel("What are you looking for?").fill("Do you offer a payment plan? I can only study evenings.");
  await page.getByLabel(/I have read the privacy notice/).check();
  await page.waitForTimeout(2200); // the server treats sub-2-second submissions as bots
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/\/apply\/thanks\?ref=NW-/);
  await page.goto("/dashboard");
  await page.getByLabel("Search by name or email").fill(who.email);
  await page.getByRole("link", { name: who.name }).click();
  await expect(page.getByRole("heading", { level: 1, name: who.name })).toBeVisible();
}

/** Wait until the agent has drafted a reply and the review card is on screen. */
export async function waitForDraft(page: Page, first: string): Promise<void> {
  await expect(page.getByRole("heading", { name: `Draft reply to ${first}` })).toBeVisible({ timeout: 45_000 });
}

export type MailpitMessage = { ID: string; Subject: string; To: { Address: string }[] };

/** Messages Mailpit holds for a recipient (empty when none arrived). */
export async function mailsTo(request: APIRequestContext, email: string): Promise<MailpitMessage[]> {
  const res = await request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:${email}` } });
  expect(res.ok()).toBe(true);
  return ((await res.json()) as { messages: MailpitMessage[] }).messages ?? [];
}

export async function mailText(request: APIRequestContext, id: string): Promise<string> {
  const res = await request.get(`${MAILPIT}/api/v1/message/${id}`);
  expect(res.ok()).toBe(true);
  return ((await res.json()) as { Text: string }).Text;
}
