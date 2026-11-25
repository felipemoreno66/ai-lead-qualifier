import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const lead = {
  items: [],
  page: 1,
  page_size: 25,
  total: 0,
};

function mockAgent(handler: (url: string, init: RequestInit) => Response) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => handler(String(url), init ?? {})));
}

beforeEach(() => {
  vi.unstubAllGlobals();
  process.env.ADMIN_API_TOKEN = "unit-test-token";
  process.env.AGENT_INTERNAL_URL = "http://agent.test";
});

describe("GET /bff/leads", () => {
  it("forwards validated filters with the server-side bearer token", async () => {
    const { GET } = await import("@/app/bff/leads/route");
    let seen: { url: string; auth: string | null } | undefined;
    mockAgent((url, init) => {
      seen = { url, auth: new Headers(init.headers).get("authorization") };
      return Response.json(lead);
    });
    const request = new Request("http://web/bff/leads?status=new,error&score_min=45&q=ana&page=2");
    const response = await GET(Object.assign(request, { nextUrl: new URL(request.url) }) as never);
    expect(response.status).toBe(200);
    expect(seen?.auth).toBe("Bearer unit-test-token");
    const url = new URL(seen!.url);
    expect(url.pathname).toBe("/admin/leads");
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ status: "new,error", score_min: "45", q: "ana", page: "2" });
  });

  it("rejects invalid input before calling the agent", async () => {
    const { GET } = await import("@/app/bff/leads/route");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const request = new Request("http://web/bff/leads?status=bogus");
    const response = await GET(Object.assign(request, { nextUrl: new URL(request.url) }) as never);
    expect(response.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("turns agent failures into JSON errors without leaking the token", async () => {
    const { GET } = await import("@/app/bff/leads/route");
    mockAgent(() => Response.json({ title: "Forbidden", detail: "Invalid token." }, { status: 403 }));
    const request = new Request("http://web/bff/leads");
    const response = await GET(Object.assign(request, { nextUrl: new URL(request.url) }) as never);
    expect(response.status).toBe(403);
    expect(await response.text()).not.toContain("unit-test-token");
  });

  it("answers 502 when the agent returns an unexpected shape", async () => {
    const { GET } = await import("@/app/bff/leads/route");
    mockAgent(() => Response.json({ nope: true }));
    const request = new Request("http://web/bff/leads");
    const response = await GET(Object.assign(request, { nextUrl: new URL(request.url) }) as never);
    expect(response.status).toBe(502);
  });
});

describe("state-changing BFF routes", () => {
  const id = "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11";
  const ctx = { params: Promise.resolve({ id }) };

  it("refuse requests without the anti-CSRF header or from another origin", async () => {
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const bare = await DELETE(new Request(`http://web/bff/leads/${id}`, { method: "DELETE" }), ctx);
    expect(bare.status).toBe(403);
    const foreign = await DELETE(
      new Request(`http://web/bff/leads/${id}`, {
        method: "DELETE",
        headers: { "x-requested-with": "lead-qualifier", origin: "https://evil.example" },
      }),
      ctx,
    );
    expect(foreign.status).toBe(403);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("answer 403, not 500, for a malformed or opaque Origin header", async () => {
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    for (const origin of ["null", "not a url", "://"]) {
      const response = await DELETE(
        new Request(`http://web/bff/leads/${id}`, {
          method: "DELETE",
          headers: { "x-requested-with": "lead-qualifier", host: "web", origin },
        }),
        ctx,
      );
      expect(response.status).toBe(403);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("accept the browser's origin when it matches the Host header", async () => {
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    mockAgent(() => new Response(null, { status: 204 }));
    const response = await DELETE(
      new Request(`http://0.0.0.0:3000/bff/leads/${id}`, {
        method: "DELETE",
        headers: { "x-requested-with": "lead-qualifier", origin: "http://localhost:3000", host: "localhost:3000" },
      }),
      ctx,
    );
    expect(response.status).toBe(204);
  });

  it("delete the lead when the request is legitimate", async () => {
    const { DELETE } = await import("@/app/bff/leads/[id]/route");
    let method = "";
    mockAgent((_url, init) => {
      method = String(init.method);
      return new Response(null, { status: 204 });
    });
    const response = await DELETE(
      new Request(`http://web/bff/leads/${id}`, {
        method: "DELETE",
        headers: { "x-requested-with": "lead-qualifier", origin: "http://web" },
      }),
      ctx,
    );
    expect(response.status).toBe(204);
    expect(method).toBe("DELETE");
  });

  it("reject ids that are not UUIDs", async () => {
    const { GET } = await import("@/app/bff/leads/[id]/route");
    const response = await GET(new Request("http://web/bff/leads/abc"), { params: Promise.resolve({ id: "abc" }) });
    expect(response.status).toBe(404);
  });
});


describe("BFF routes in production", () => {
  it("each route enforces the dashboard credentials itself", async () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("DASHBOARD_USER", "ops");
    vi.stubEnv("DASHBOARD_PASSWORD", "pw");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const id = "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11";
    const ctx = { params: Promise.resolve({ id }) };
    const list = await import("@/app/bff/leads/route");
    const one = await import("@/app/bff/leads/[id]/route");
    const re = await import("@/app/bff/leads/[id]/retrigger/route");
    const ws = await import("@/app/bff/workspaces/route");
    const review = await import("@/app/bff/leads/[id]/review/route");
    const runs = await import("@/app/bff/leads/[id]/runs/route");
    const bare = new Request("http://web/bff/leads");
    const withNext = Object.assign(bare, { nextUrl: new URL(bare.url) }) as never;
    const mutate = { "x-requested-with": "lead-qualifier" };
    const responses = [
      await list.GET(withNext),
      await one.GET(new Request(`http://web/bff/leads/${id}`), ctx),
      await one.DELETE(new Request(`http://web/bff/leads/${id}`, { method: "DELETE", headers: mutate }), ctx),
      await re.POST(new Request(`http://web/bff/leads/${id}/retrigger`, { method: "POST", headers: mutate }), ctx),
      await ws.GET(new Request("http://web/bff/workspaces")),
      await review.POST(
        new Request(`http://web/bff/leads/${id}/review`, { method: "POST", headers: mutate, body: "{}" }),
        ctx,
      ),
      await runs.GET(new Request(`http://web/bff/leads/${id}/runs`), ctx),
    ];
    expect(responses.map((r) => r.status)).toEqual([401, 401, 401, 401, 401, 401, 401]);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
});
