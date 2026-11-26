import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SignOutButton } from "@/features/auth/sign-out-button";

afterEach(() => vi.unstubAllGlobals());

function setup(status: number) {
  const queryClient = new QueryClient();
  queryClient.setQueryData(["leads"], [{ id: 1 }]);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
  const replace = vi.fn();
  vi.stubGlobal("location", { replace });
  render(
    <QueryClientProvider client={queryClient}>
      <SignOutButton />
    </QueryClientProvider>,
  );
  return { queryClient, replace };
}

describe("SignOutButton", () => {
  it("clears the client cache and navigates hard once the POST succeeded", async () => {
    const { queryClient, replace } = setup(200);
    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(queryClient.getQueryData(["leads"])).toBeUndefined();
  });

  it("does not pretend to be signed out when the POST fails", async () => {
    const { queryClient, replace } = setup(500);
    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not sign out/i);
    expect(replace).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(["leads"])).toBeDefined();
  });
});
