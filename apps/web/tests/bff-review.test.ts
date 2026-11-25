import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const id = "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11";
const ctx = { params: Promise.resolve({ id }) };
const mutate = { "x-requested-with": "lead-qualifier", "content-type": "application/json", origin: "http://web" };
const result = { lead_id: id, status: "approved", message_id: "6a1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a22" };

const post = (body: unknown, headers: Record<string, string> = mutate) =>
  new Request(`http://web/bff/leads/${id}/review`, {
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

describe("POST /bff/leads/[id]/review", () => {
  it("forwards a validated review with the server-side token", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    let seen: { url: string; auth: string | null; body: unknown } | undefined;
    agent((url, init) => {
      seen = {
        url,
        auth: new Headers(init.headers).get("authorization"),
        body: JSON.parse(String(init.body)),
      };
      return Response.json(result);
    });
    // `stolen` is not part of the contract and must not reach the agent.
    const response = await POST(post({ action: "edit", subject: "Hi", body: "Hello", override: true, stolen: "x" }), ctx);
    expect(response.status).toBe(200);
    expect(seen?.url).toBe(`http://agent.test/admin/leads/${id}/review`);
    expect(seen?.auth).toBe("Bearer unit-test-token");
    expect(seen?.body).toMatchObject({ action: "edit", subject: "Hi", body: "Hello", override: true });
    expect(seen?.body).not.toHaveProperty("stolen");
  });

  it("refuses requests without the anti-CSRF header or from another origin", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    const spy = agent(() => Response.json(result));
    const bare = await POST(post({ action: "approve" }, { "content-type": "application/json" }), ctx);
    const foreign = await POST(post({ action: "approve" }, { ...mutate, origin: "https://evil.example" }), ctx);
    expect([bare.status, foreign.status]).toEqual([403, 403]);
    expect(spy).not.toHaveBeenCalled();
  });

  it("refuses requests the browser marks as cross-site and ignores a forged forwarded host", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    const spy = agent(() => Response.json(result));
    for (const site of ["cross-site", "same-site", "none"]) {
      expect((await POST(post({ action: "approve" }, { ...mutate, "sec-fetch-site": site }), ctx)).status).toBe(403);
    }
    const forged = { ...mutate, origin: "https://evil.example", "x-forwarded-host": "evil.example", host: "web" };
    expect((await POST(post({ action: "approve" }, forged), ctx)).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
    vi.stubEnv("TRUST_FORWARDED_HOST", "true");
    expect((await POST(post({ action: "approve" }, forged), ctx)).status).toBe(200);
    expect((await POST(post({ action: "approve" }, { ...mutate, "sec-fetch-site": "same-origin" }), ctx)).status).toBe(200);
  });

  it("validates the body before calling the agent", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    const spy = agent(() => Response.json(result));
    const bad: unknown[] = [
      "not json",
      {},
      { action: "delete" },
      { action: "edit" },
      { action: "edit", body: "" },
      { action: "edit", body: "ok", subject: "x".repeat(151) },
      { action: "edit", body: "x".repeat(4001) },
      { action: "reject", note: "x".repeat(501) },
      { action: "approve", override: "yes" },
    ];
    for (const body of bad) expect((await POST(post(body), ctx)).status).toBe(400);
    expect((await POST(post("x".repeat(40_000)), ctx)).status).toBe(413);
    // 7,000 four-byte characters are fewer than 24,000 characters but more than 24,000 bytes.
    expect((await POST(post(JSON.stringify({ action: "reject", note: "\u{1F600}".repeat(7000) })), ctx)).status).toBe(413);
    const declared = await POST(post({ action: "approve" }, { ...mutate, "content-length": "99999" }), ctx);
    expect(declared.status).toBe(413);
    expect((await POST(post({ action: "approve" }), { params: Promise.resolve({ id: "abc" }) })).status).toBe(404);
    expect(spy).not.toHaveBeenCalled();
  });

  it("passes the draft-check problems of a 422 through to the browser", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    agent(() =>
      Response.json(
        {
          title: "Validation failed",
          detail: "The message does not pass the draft checks.",
          errors: [{ code: "disallowed_link", message: "link to a domain that is not allowed: evil.example" }, "junk"],
        },
        { status: 422 },
      ),
    );
    const response = await POST(post({ action: "approve" }), ctx);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(body.errors).toEqual([
      { code: "disallowed_link", message: "link to a domain that is not allowed: evil.example" },
    ]);
  });

  it("keeps a 409 conflict as 409 and hides agent crashes behind a 502", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    agent(() => Response.json({ title: "Conflict", detail: "A lead in status 'sent' cannot be reviewed." }, { status: 409 }));
    expect((await POST(post({ action: "reject" }), ctx)).status).toBe(409);
    agent(() =>
      Response.json({ title: "Internal error", detail: "Traceback: password=hunter2 at /app/x.py" }, { status: 500 }),
    );
    const crashed = await POST(post({ action: "reject" }), ctx);
    expect(crashed.status).toBe(502);
    const text = await crashed.text();
    expect(text).not.toMatch(/Traceback|hunter2|x\.py/);
  });

  it("is protected like every other route in production", async () => {
    const { POST } = await import("@/app/bff/leads/[id]/review/route");
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("DASHBOARD_USER", "ops");
    vi.stubEnv("DASHBOARD_PASSWORD", "pw");
    const spy = agent(() => Response.json(result));
    expect((await POST(post({ action: "approve" }), ctx)).status).toBe(401);
    const authed = await POST(
      post({ action: "approve" }, { ...mutate, authorization: `Basic ${Buffer.from("ops:pw").toString("base64")}` }),
      ctx,
    );
    expect(authed.status).toBe(200);
    expect(spy).toHaveBeenCalledOnce();
  });
});

describe("GET /bff/leads/[id]/runs", () => {
  it("returns the validated runs and rejects bad ids and shapes", async () => {
    const { GET } = await import("@/app/bff/leads/[id]/runs/route");
    agent(() => Response.json([]));
    const ok = await GET(new Request(`http://web/bff/leads/${id}/runs`), ctx);
    expect(ok.status).toBe(200);
    expect(await ok.json()).toEqual([]);
    expect((await GET(new Request("http://web/x"), { params: Promise.resolve({ id: "abc" }) })).status).toBe(404);
    agent(() => Response.json({ nope: true }));
    expect((await GET(new Request(`http://web/bff/leads/${id}/runs`), ctx)).status).toBe(502);
  });
});
