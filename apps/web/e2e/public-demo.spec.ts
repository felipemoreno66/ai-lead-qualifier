import { expect, test } from "@playwright/test";
import { applicant, applyAndOpen, waitForDraft } from "./helpers";

// Runs only against the public-demo stack: E2E_PUBLIC_DEMO=true E2E_BASE_URL=http://127.0.0.1:3100
// (docker-compose.public.yml, PUBLIC_DEMO=true). Visitor IPs are faked with X-Forwarded-For so a
// rerun does not hit the previous run's limits.
test.skip(process.env.E2E_PUBLIC_DEMO !== "true", "needs the public-demo stack");
test.describe.configure({ mode: "serial" });

const mutate = { "x-requested-with": "lead-qualifier", "content-type": "application/json" };
const visitor = () => ({ "x-forwarded-for": `198.51.100.${Math.floor(Math.random() * 250) + 1}` });

test("every page carries the public demo banner and strict headers", async ({ page }) => {
  const response = await page.goto("/dashboard");
  await expect(page.getByRole("note").filter({ hasText: "Public demo" })).toContainText(
    "Fictional data, resets every night",
  );
  expect(response?.headers()["strict-transport-security"]).toContain("max-age=");
  expect(response?.headers()["content-security-policy"]).toContain("connect-src 'self';");
  await page.goto("/w/northwind-academy/apply");
  await expect(page.getByRole("note").filter({ hasText: "Public demo" })).toBeVisible();
  await expect(page.getByText("Fictional demo: use made-up details")).toBeVisible();
});

test("the dashboard is open and the seeded data is loaded", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("link", { name: "Mateo Alvarez" })).toBeVisible();
  await page.getByRole("link", { name: "Mateo Alvarez" }).click();
  await expect(page.getByRole("heading", { name: "Draft reply to Mateo" })).toBeVisible();
});

test("deleting a lead is disabled in the UI and refused by the server", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByRole("link", { name: "Mateo Alvarez" }).click();
  await expect(page.getByText("Deleting leads is disabled in the public demo.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete this lead" })).toHaveCount(0);
  const id = page.url().split("/").pop();
  const response = await page.request.delete(`/bff/leads/${id}`, { headers: { ...mutate, ...visitor() } });
  expect(response.status()).toBe(403);
});

test("the agent API is not reachable from outside", async ({ request }) => {
  await expect(request.get("http://127.0.0.1:8000/healthz", { timeout: 3000 })).rejects.toThrow();
});

test("the public form works through the web server and the lead gets a draft", async ({ page }) => {
  const posts: string[] = [];
  page.on("request", (r) => r.method() === "POST" && posts.push(r.url()));
  const who = applicant("Visitor");
  await applyAndOpen(page, who);
  await waitForDraft(page, "Visitor");
  expect(posts.some((u) => new URL(u).pathname === "/api/leads/northwind-academy")).toBe(true);
  expect(posts.every((u) => new URL(u).origin === new URL(page.url()).origin)).toBe(true);
});

test("Ask the docs answers and is rate limited per visitor", async ({ page }) => {
  const headers = { ...mutate, ...visitor() };
  const ask = () =>
    page.request.post("/bff/kb/northwind-academy/ask", {
      headers,
      data: { question: "Do you offer scholarships?" },
    });
  const first = await ask();
  expect(first.status()).toBe(200);
  let limited = 0;
  for (let i = 0; i < 12; i++) if ((await ask()).status() === 429) limited += 1;
  expect(limited).toBeGreaterThan(0);
  const other = await page.request.post("/bff/kb/northwind-academy/ask", {
    headers: { ...mutate, ...visitor() },
    data: { question: "Is there a refund policy?" },
  });
  expect(other.status()).toBe(200);
});

test("a chunked oversized body gets 413 and a hidden workspace gets 404", async ({ page }) => {
  const big = await page.request.post("/bff/kb/northwind-academy/ask", {
    headers: { ...mutate, ...visitor() },
    data: { question: "x".repeat(5000) },
  });
  expect(big.status()).toBe(413);
  const hidden = await page.request.get("/bff/metrics?workspace=not-a-workspace", { headers: visitor() });
  expect(hidden.status()).toBe(404);
});
