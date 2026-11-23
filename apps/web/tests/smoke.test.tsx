import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Home from "@/app/page";

describe("home", () => {
  it("links to the dashboard", () => {
    render(<Home />);
    expect(screen.getByRole("link", { name: /open the dashboard/i })).toHaveAttribute(
      "href",
      "/dashboard",
    );
  });
});
