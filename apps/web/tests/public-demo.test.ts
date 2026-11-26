import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("server-only", () => ({}));

const id = "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11";
const ctx = { params: Promise.resolve({ id }) };
const mutate = { "x-requested-with": "lead-qualifier", "content-type": "application/json", origin: "http://web" };

function agent(handler: (url: string, init: RequestInit) => Response) {
  const spy = vi.fn(async (url: string, init: RequestInit) => handler(String(url), init ?? {}));
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(async () => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  process.env.ADMIN_API_TOKEN = "unit-test-token";
  process.env.AGENT_INTERNAL_URL = "http://agent.test";
  (await import("@/lib/public-demo")).resetDemoLimits();
});
afterEach(() => vi.unstubAllEnvs());

describe("public demo flag and limits", () => {
  it("is off unless PUBLIC_DEMO is exactly true", async () => {
    const { isPublicDemo } = await import("@/lib/public-demo");
    expect(isPublicDemo({})).toBe(false);
    expect(isPublicDemo({ PUBLIC_DEMO: "1" })).toBe(false);
    expect(isPublicDemo({ PUBLIC_DEMO: "true" })).toBe(true);
  });

  it("believes only the last X-Forwarded-For entry", async () => {
    const { clientIp } = await import("@/lib/public-demo");
    const request = (xff?: string) => new Request("http://web/", { headers: xff ? { "x-forwarded-for": xff } : {} });
    expect(clientIp(request("6.6.6.6, 203.0.113.9"))).toBe("203.0.113.9");
    expect(clientIp(request())).toBe("unknown");
  });

  it("limits per IP and bucket, then recovers after the window", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_ASK_PER_HOUR", "2");
    const { demoRateLimit } = await import("@/lib/public-demo");
    const from = (ip: string) => new Request("http://web/", { headers: { "x-forwarded-for": ip } });
    const t0 = 1_000_000;
    expect(demoRateLimit(from("1.1.1.1"), "ask", t0)).toBeNull();
    expect(demoRateLimit(from("1.1.1.1"), "ask", t0)).toBeNull();
    const blocked = demoRateLimit(from("1.1.1.1"), "ask", t0 + 1000);
    expect(blocked?.status).toBe(429);
    expect(Number(blocked?.headers.get("retry-after"))).toBeGreaterThan(3500);
    expect(demoRateLimit(from("2.2.2.2"), "ask", t0)).toBeNull(); // another visitor
    expect(demoRateLimit(from("1.1.1.1"), "review", t0)).toBeNull(); // another bucket
    expect(demoRateLimit(from("1.1.1.1"), "ask", t0 + 3_600_001)).toBeNull();
  });

  it("never limits outside the public demo", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    const { demoRateLimit } = await import("@/lib/public-demo");
    for (let i = 0; i < 100; i++) expect(demoRateLimit(new Request("http://web/"), "ask")).toBeNull();
  });
});

describe("BFF in the public demo", () => {
  it("refuses to delete a lead and never calls the agent", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    const spy = agent(() => new Response(null, { status: 204 }));
    const response = await DELETE(
      new Request(`http://web/bff/leads/${id}`, { method: "DELETE", headers: mutate }),
      ctx,
    );
    expect(response.status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });

  it("still deletes outside the public demo", async () => {
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    const spy = agent(() => new Response(null, { status: 204 }));
    const response = await DELETE(
      new Request(`http://web/bff/leads/${id}`, { method: "DELETE", headers: mutate }),
      ctx,
    );
    expect(response.status).toBe(204);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("rate limits review actions per visitor", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_REVIEW_PER_HOUR", "1");
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    const spy = agent(() =>
      Response.json({ lead_id: id, status: "approved", message_id: "6a1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a22" }),
    );
    const review = () =>
      new Request(`http://web/bff/leads/${id}/review`, {
        method: "POST",
        headers: { ...mutate, "x-forwarded-for": "9.9.9.9" },
        body: JSON.stringify({ action: "approve" }),
      });
    expect((await POST(review(), ctx)).status).toBe(200);
    expect((await POST(review(), ctx)).status).toBe(429);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("rate limits Ask the docs", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_ASK_PER_HOUR", "1");
    const { POST } = await import("@/app/bff/kb/[slug]/ask/route");
    agent(() => new Response("{}", { status: 502 }));
    const ask = () =>
      new Request("http://web/bff/kb/northwind-academy/ask", {
        method: "POST",
        headers: { ...mutate, "x-forwarded-for": "9.9.9.9" },
        body: JSON.stringify({ question: "How much is it?" }),
      });
    const slug = { params: Promise.resolve({ slug: "northwind-academy" }) };
    expect((await POST(ask(), slug)).status).not.toBe(429);
    expect((await POST(ask(), slug)).status).toBe(429);
  });
});

describe("POST /api/leads/[slug] (intake relay)", () => {
  const slug = { params: Promise.resolve({ slug: "northwind-academy" }) };
  const submit = (headers: Record<string, string> = {}) =>
    new Request("http://web/api/leads/northwind-academy", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://web", "x-forwarded-for": "7.7.7.7", ...headers },
      body: JSON.stringify({ fields: {} }),
    });

  it("does not exist outside the public demo", async () => {
    const { POST } = await import("@/app/api/leads/[slug]/route");
    expect((await POST(submit(), slug)).status).toBe(404);
  });

  it("relays to the agent with the visitor IP and passes the status through", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { POST } = await import("@/app/api/leads/[slug]/route");
    let seen: { url: string; headers: Headers } | undefined;
    agent((url, init) => {
      seen = { url, headers: new Headers(init.headers) };
      return Response.json({ reference: "NWA-1" }, { status: 202 });
    });
    const response = await POST(submit({ "x-forwarded-for": "6.6.6.6, 7.7.7.7" }), slug);
    expect(response.status).toBe(202);
    expect(seen?.url).toBe("http://agent.test/api/leads/northwind-academy");
    expect(seen?.headers.get("x-forwarded-for")).toBe("7.7.7.7");
  });

  it("refuses cross-site posts and limits the visitor", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_INTAKE_PER_HOUR", "1");
    const { POST } = await import("@/app/api/leads/[slug]/route");
    const spy = agent(() => Response.json({ reference: "NWA-1" }, { status: 202 }));
    expect((await POST(submit({ origin: "https://evil.example" }), slug)).status).toBe(403);
    expect((await POST(submit(), slug)).status).toBe(202);
    expect((await POST(submit(), slug)).status).toBe(429);
    expect(spy).toHaveBeenCalledOnce();
  });
});

describe("proxy headers in the public demo", () => {
  it("adds HSTS and isolation headers and drops the agent from connect-src", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("PUBLIC_API_BASE_URL", "http://localhost:8000");
    const { proxy } = await import("../proxy");
    const res = proxy(new NextRequest("http://web/dashboard"));
    expect(res.headers.get("Strict-Transport-Security")).toContain("max-age=31536000");
    expect(res.headers.get("Cross-Origin-Opener-Policy")).toBe("same-origin");
    expect(res.headers.get("Content-Security-Policy")).toContain("connect-src 'self';");
    expect(res.headers.get("Content-Security-Policy")).not.toContain("localhost:8000");
  });

  it("leaves a normal instance unchanged", async () => {
    vi.stubEnv("PUBLIC_API_BASE_URL", "http://localhost:8000");
    const { proxy } = await import("../proxy");
    const res = proxy(new NextRequest("http://web/dashboard"));
    expect(res.headers.get("Strict-Transport-Security")).toBeNull();
    expect(res.headers.get("Content-Security-Policy")).toContain("localhost:8000");
  });
});

describe("hardening", () => {
  it("reduces IPv6 clients to their /64 and unwraps IPv4-mapped addresses", async () => {
    const { networkKey } = await import("@/lib/public-demo");
    expect(networkKey("203.0.113.9")).toBe("203.0.113.9");
    expect(networkKey("::ffff:203.0.113.9")).toBe("203.0.113.9");
    const a = networkKey("2001:db8:1:2:aaaa:bbbb:cccc:dddd");
    expect(a).toBe(networkKey("2001:DB8:1:2::1"));
    expect(a).not.toBe(networkKey("2001:db8:1:3::1"));
    expect(networkKey("2001:db8::1")).toBe("2001:db8:0:0::/64");
  });

  it("applies one limit to a whole /64 and a global ceiling to everyone", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_ASK_PER_HOUR", "2");
    vi.stubEnv("DEMO_GLOBAL_ASK_PER_HOUR", "3");
    const { demoRateLimit } = await import("@/lib/public-demo");
    const from = (ip: string) => new Request("http://web/", { headers: { "x-forwarded-for": ip } });
    expect(demoRateLimit(from("2001:db8:1:2::1"), "ask", 1)).toBeNull();
    expect(demoRateLimit(from("2001:db8:1:2::2"), "ask", 1)).toBeNull();
    expect(demoRateLimit(from("2001:db8:1:2::3"), "ask", 1)?.status).toBe(429); // same /64
    expect(demoRateLimit(from("198.51.100.1"), "ask", 1)).toBeNull(); // 3rd of 3 globally
    expect(demoRateLimit(from("198.51.100.2"), "ask", 1)?.status).toBe(429); // global ceiling
  });

  it("fails closed when the per-visitor map is full instead of forgetting counters", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_REVIEW_PER_HOUR", "1");
    vi.stubEnv("DEMO_GLOBAL_REVIEW_PER_HOUR", "1000000");
    const { demoRateLimit } = await import("@/lib/public-demo");
    const from = (ip: string) => new Request("http://web/", { headers: { "x-forwarded-for": ip } });
    const known = from("10.0.0.1");
    expect(demoRateLimit(known, "review", 1)).toBeNull();
    for (let i = 0; i < 10_000; i++) demoRateLimit(from(`172.${i >> 8}.${i & 255}.1`), "review", 1);
    expect(demoRateLimit(from("192.0.2.1"), "review", 1)?.status).toBe(429); // new key, map full
    expect(demoRateLimit(known, "review", 1)?.status).toBe(429); // old counter survived the flood
  });
});

describe("global ceiling", () => {
  it("is not consumed by a visitor that is over its own limit", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubEnv("DEMO_LIMIT_ASK_PER_HOUR", "1");
    vi.stubEnv("DEMO_GLOBAL_ASK_PER_HOUR", "3");
    const { demoRateLimit } = await import("@/lib/public-demo");
    const from = (ip: string) => new Request("http://web/", { headers: { "x-forwarded-for": ip } });
    expect(demoRateLimit(from("203.0.113.1"), "ask", 1)).toBeNull();
    for (let i = 0; i < 50; i++) expect(demoRateLimit(from("203.0.113.1"), "ask", 1)?.status).toBe(429);
    // The abuser used one unit of the global allowance, so two other visitors still fit.
    expect(demoRateLimit(from("203.0.113.2"), "ask", 1)).toBeNull();
    expect(demoRateLimit(from("203.0.113.3"), "ask", 1)).toBeNull();
    expect(demoRateLimit(from("203.0.113.4"), "ask", 1)?.status).toBe(429);
  });
});

describe("readBoundedText", () => {
  const post = (body: BodyInit | null, headers: Record<string, string> = {}) =>
    new Request("http://web/", { method: "POST", headers, body, duplex: "half" } as RequestInit);

  it("reads a body within the limit", async () => {
    const { readBoundedText } = await import("@/lib/api/bounded-body");
    expect(await readBoundedText(post("hello"), 10)).toBe("hello");
    expect(await readBoundedText(post(null), 10)).toBe("");
  });

  it("stops reading a stream that grows past the limit, whatever Content-Length says", async () => {
    const { readBoundedText } = await import("@/lib/api/bounded-body");
    let pulled = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulled += 1;
        controller.enqueue(new Uint8Array(1024));
        if (pulled > 1000) controller.close();
      },
    });
    const request = post(stream, { "content-length": "abc" });
    expect(await readBoundedText(request, 4096)).toBeNull();
    expect(pulled).toBeLessThan(20);
  });

  it("refuses a declared size over the limit without reading", async () => {
    const { readBoundedText } = await import("@/lib/api/bounded-body");
    expect(await readBoundedText(post("x", { "content-length": "99999" }), 100)).toBeNull();
  });

  it("makes the intake relay answer 413 for an oversized body", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { POST } = await import("@/app/api/leads/[slug]/route");
    const spy = agent(() => Response.json({}, { status: 202 }));
    const response = await POST(
      new Request("http://web/api/leads/northwind-academy", {
        method: "POST",
        headers: { "content-type": "application/json", origin: "http://web", "x-forwarded-for": "5.5.5.5" },
        body: "x".repeat(20_000),
      }),
      { params: Promise.resolve({ slug: "northwind-academy" }) },
    );
    expect(response.status).toBe(413);
    expect(spy).not.toHaveBeenCalled();
  });
});
