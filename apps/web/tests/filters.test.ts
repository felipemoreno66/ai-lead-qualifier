import { describe, expect, it } from "vitest";
import {
  hasActiveFilters,
  parseFilters,
  toApiParams,
  toUrlParams,
  type LeadFilters,
} from "@/lib/leads/filters";

const parse = (qs: string) => parseFilters(new URLSearchParams(qs));

describe("filters <-> URL", () => {
  it("round-trips every filter", () => {
    const filters: LeadFilters = {
      workspace: "northwind-academy",
      statuses: ["new", "error"],
      band: "warm",
      q: "ana",
      page: 3,
    };
    expect(parse(toUrlParams(filters).toString())).toEqual(filters);
  });

  it("omits defaults from the browser URL", () => {
    expect(toUrlParams({ statuses: [], band: "any", q: "  ", page: 1 }).toString()).toBe("");
  });

  it("accepts repeated and comma-separated statuses and drops unknown ones", () => {
    expect(parse("status=new,sent&status=error&status=bogus").statuses).toEqual(["new", "sent", "error"]);
  });

  it("falls back to safe defaults for malformed values", () => {
    const f = parse("score=huge&page=-4&q=" + "x".repeat(300));
    expect(f.band).toBe("any");
    expect(f.page).toBe(1);
    expect(f.q).toHaveLength(100);
    expect(parse("page=abc").page).toBe(1);
  });

  it("maps score bands to the API range", () => {
    expect(toApiParams({ statuses: [], band: "hot", q: "", page: 1 }).get("score_min")).toBe("75");
    const warm = toApiParams({ statuses: [], band: "warm", q: "", page: 1 });
    expect([warm.get("score_min"), warm.get("score_max")]).toEqual(["45", "74"]);
    const cold = toApiParams({ statuses: [], band: "cold", q: "", page: 1 });
    expect([cold.get("score_min"), cold.get("score_max")]).toEqual([null, "44"]);
  });

  it("builds the agent query with paging and search", () => {
    const p = toApiParams({ workspace: "w", statuses: ["new"], band: "any", q: " ana ", page: 2 });
    expect(Object.fromEntries(p)).toEqual({ workspace: "w", status: "new", q: "ana", page: "2", page_size: "25" });
  });

  it("knows when filters are active", () => {
    expect(hasActiveFilters({ statuses: [], band: "any", q: "", page: 1 })).toBe(false);
    expect(hasActiveFilters({ statuses: [], band: "any", q: "x", page: 1 })).toBe(true);
  });
});
