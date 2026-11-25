import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const slug = "northwind-academy";
const ctx = { params: Promise.resolve({ slug }) };
const mutate = { "x-requested-with": "lead-qualifier", "content-type": "application/json", origin: "http://web" };
const entry = {
  id: "6a1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a22",
  question: "How much is the bootcamp?",
  answer: "USD 4,900.",
  covered: true,
  citations: [
    {
      chunk_id: "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11",
      document_path: "02-pricing.md",
      document_title: "Pricing",
      heading_path: "Pricing > Bootcamp",
      quote: "The bootcamp costs USD 4,900.",
    },
  ],
  created_at: "2026-11-23T12:00:00Z",
};

const post = (body: unknown, headers: Record<string, string> = mutate) =>
  new Request(`http://web/bff/kb/${slug}/ask`, {
    method: "POST",
    headers,
    body: typeof body === "string" ? body : JSON.stringify(body),
  });

function agent(handler: (url: string, init: RequestInit) => Response) {
  const spy = vi.fn(async (url: string, init: RequestInit) => handler(String(url), init ?? {}));
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  process.env.ADMIN_API_TOKEN = "unit-test-token";
  process.env.AGENT_INTERNAL_URL = "http://agent.test";
});

describe("POST /bff/kb/[slug]/ask", () => {
  it("forwards only the validated question with the server-side token", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    let seen: { url: string; auth: string | null; body: unknown } | undefined;
    agent((url, init) => {
      seen = { url, auth: new Headers(init.headers).get("authorization"), body: JSON.parse(String(init.body)) };
      return Response.json(entry);
    });
    const response = await POST(post({ question: "  How much is the bootcamp?  ", language: "en", stolen: "x" }), ctx);
    expect(response.status).toBe(200);
    expect((await response.json()).citations[0].document_title).toBe("Pricing");
    expect(seen?.url).toBe(`http://agent.test/admin/kb/${slug}/ask`);
    expect(seen?.auth).toBe("Bearer unit-test-token");
    expect(seen?.body).toEqual({ question: "How much is the bootcamp?", language: "en" });
  });

  it("refuses requests without the anti-CSRF header, from another origin or marked cross-site", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    const spy = agent(() => Response.json(entry));
    const q = { question: "How much is it?" };
    expect((await POST(post(q, { "content-type": "application/json" }), ctx)).status).toBe(403);
    expect((await POST(post(q, { ...mutate, origin: "https://evil.example" }), ctx)).status).toBe(403);
    for (const site of ["cross-site", "same-site", "none"]) {
      expect((await POST(post(q, { ...mutate, "sec-fetch-site": site }), ctx)).status).toBe(403);
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("validates the body and the slug before calling the agent", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    const spy = agent(() => Response.json(entry));
    const bad: unknown[] = [
      "not json",
      {},
      { question: "hi" },
      { question: "x".repeat(501) },
      { question: "How much?", language: "english" },
      { question: 42 },
    ];
    for (const body of bad) expect((await POST(post(body), ctx)).status).toBe(400);
    expect((await POST(post("x".repeat(5000)), ctx)).status).toBe(413);
    expect((await POST(post({ question: "How much?" }, { ...mutate, "content-length": "99999" }), ctx)).status).toBe(413);
    for (const evil of ["../admin", "A_B", "x/../y", "UPPER"]) {
      expect((await POST(post({ question: "How much?" }), { params: Promise.resolve({ slug: evil }) })).status).toBe(404);
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("passes rate limits and unavailable providers through and hides agent crashes", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    const q = { question: "How much?" };
    agent(() => Response.json({ title: "Too many requests", detail: "Please try again later." }, { status: 429 }));
    expect((await POST(post(q), ctx)).status).toBe(429);
    agent(() => Response.json({ title: "Service unavailable", detail: "Try again in a moment." }, { status: 503 }));
    expect((await POST(post(q), ctx)).status).toBe(502);
    agent(() => Response.json({ title: "Internal error", detail: "Traceback: password=hunter2" }, { status: 500 }));
    const crashed = await POST(post(q), ctx);
    expect(crashed.status).toBe(502);
    expect(await crashed.text()).not.toMatch(/Traceback|hunter2/);
  });

  it("answers with an unexpected shape as a 502, never as data", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    agent(() => Response.json({ answer: "x" }));
    expect((await POST(post({ question: "How much?" }), ctx)).status).toBe(502);
  });

  it("is protected like every other route in production", async () => {
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("DASHBOARD_USER", "ops");
    vi.stubEnv("DASHBOARD_PASSWORD", "pw");
    const spy = agent(() => Response.json(entry));
    expect((await POST(post({ question: "How much?" }), ctx)).status).toBe(401);
    const auth = `Basic ${Buffer.from("ops:pw").toString("base64")}`;
    expect((await POST(post({ question: "How much?" }, { ...mutate, authorization: auth }), ctx)).status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe("GET /bff/kb/[slug]/queries", () => {
  const get = (headers: Record<string, string> = {}) =>
    new Request(`http://web/bff/kb/${slug}/queries`, { headers });

  it("returns the recent questions and checks the slug", async () => {
    const { GET } = await import("@/app/bff/kb/[slug]/queries/route");
    let url = "";
    agent((u) => {
      url = u;
      return Response.json([entry]);
    });
    const response = await GET(get(), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toHaveLength(1);
    expect(url).toBe(`http://agent.test/admin/kb/${slug}/queries?limit=10`);
    expect((await GET(get(), { params: Promise.resolve({ slug: "../x" }) })).status).toBe(404);
  });
});
