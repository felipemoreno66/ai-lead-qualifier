import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApplyForm } from "@/features/apply/apply-form";
import type { PublicWorkspaceConfig } from "@/lib/api/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const config: PublicWorkspaceConfig = JSON.parse(
  readFileSync(join(__dirname, "../../../packages/contracts/fixtures/northwind-public-config.json"), "utf8"),
);

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Full name"), "Ana Torres");
  await user.type(screen.getByLabelText("Email"), "ana@example.com");
  await user.selectOptions(screen.getByLabelText("Country"), "CO");
  await user.click(screen.getByLabelText("Data & AI Course"));
  await user.type(screen.getByLabelText("Career goal"), "Move into data work");
  await user.click(screen.getByLabelText("USD 500–2,500"));
  await user.click(screen.getByLabelText("5–10 h"));
}

describe("ApplyForm", () => {
  beforeEach(() => push.mockReset());
  afterEach(() => vi.unstubAllGlobals());

  const setup = () => {
    const user = userEvent.setup();
    render(<ApplyForm config={config} apiBase="http://api.test" initialLocale="en" />);
    return user;
  };

  it("renders one control per field type, grouped in sections", () => {
    setup();
    expect(screen.getByRole("group", { name: /About you/ })).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("type", "email");
    expect(screen.getByLabelText("Country").tagName).toBe("SELECT");
    expect(screen.getByRole("radiogroup", { name: /Budget/ })).toBeInTheDocument();
    expect(screen.getByLabelText(/What are you looking for/).tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText(/Company website/, { selector: "input" })).toHaveAttribute("tabindex", "-1");
  });

  it("shows field errors and does not call the API when invalid", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = setup();
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please check these fields");
    expect(screen.getAllByText("This field is required.").length).toBeGreaterThan(1);
    expect(screen.getByText("Check this answer.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires consent", async () => {
    vi.stubGlobal("fetch", vi.fn());
    const user = setup();
    await fillValid(user);
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByLabelText(/I have read the privacy notice/)).toHaveAttribute("aria-invalid", "true");
  });

  it("posts the typed payload and goes to the thank-you page", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ received: true, reference: "NW-ABC234" }), { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = setup();
    await fillValid(user);
    await user.click(screen.getByLabelText(/I have read the privacy notice/));
    await user.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/leads/northwind-academy");
    const body = JSON.parse(init.body);
    expect(body.fields).toMatchObject({ name: "Ana Torres", country: "CO", program: "data-ai-course", budget: "500-2500" });
    expect(body).toMatchObject({ consent: true, consent_notice_version: config.privacy.version, locale: "en", hp_company_website: "" });
    expect(Number.isNaN(Date.parse(body.form_rendered_at))).toBe(false);
    expect(push).toHaveBeenCalledWith("/w/northwind-academy/apply/thanks?ref=NW-ABC234&lang=en");
  });

  it("maps server validation errors back to the fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ errors: [{ loc: ["fields", "email"], msg: "x" }] }), { status: 422 }),
      ),
    );
    const user = setup();
    await fillValid(user);
    await user.click(screen.getByLabelText(/I have read the privacy notice/));
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(push).not.toHaveBeenCalled();
  });

  it("explains rate limiting and network failures", async () => {
    const user = setup();
    await fillValid(user);
    await user.click(screen.getByLabelText(/I have read the privacy notice/));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 429 })));
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/Too many attempts/)).toBeInTheDocument();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText(/could not reach the server/)).toBeInTheDocument();
  });

  it("switches labels to Spanish", async () => {
    const user = setup();
    await user.click(screen.getByRole("button", { name: "ES" }));
    expect(screen.getByLabelText("Nombre completo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar solicitud" })).toBeInTheDocument();
  });
});
