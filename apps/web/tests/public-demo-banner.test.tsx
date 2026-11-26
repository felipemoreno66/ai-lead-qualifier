import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({ connection: async () => undefined }));

afterEach(() => vi.unstubAllEnvs());

describe("PublicDemoBanner", () => {
  it("states that the data is fictional and resets nightly", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { PublicDemoBanner } = await import("@/components/public-demo-banner");
    render(await PublicDemoBanner());
    expect(screen.getByRole("note").textContent).toMatch(/Public demo.*Fictional data, resets every night/);
  });

  it("renders nothing on a normal instance", async () => {
    const { PublicDemoBanner } = await import("@/components/public-demo-banner");
    expect(await PublicDemoBanner()).toBeNull();
  });
});
