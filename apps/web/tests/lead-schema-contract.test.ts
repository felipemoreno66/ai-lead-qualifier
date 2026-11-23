import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { PublicWorkspaceConfig } from "@/lib/api/types";
import { buildLeadSchema, errorFields } from "@/lib/forms/build-lead-schema";

const FIXTURES = join(__dirname, "../../../packages/contracts/fixtures");
const config: PublicWorkspaceConfig = JSON.parse(
  readFileSync(join(FIXTURES, "northwind-public-config.json"), "utf8"),
);
const schema = buildLeadSchema(config.form.fields);

type Fixture = {
  description: string;
  fields: Record<string, unknown>;
  expect: { valid: boolean; error_fields: string[] };
};

const cases = ["valid", "invalid"].flatMap((group) =>
  readdirSync(join(FIXTURES, "lead-submissions", group)).map((file) => ({
    name: `${group}/${file.replace(".json", "")}`,
    fixture: JSON.parse(
      readFileSync(join(FIXTURES, "lead-submissions", group, file), "utf8"),
    ) as Fixture,
  })),
);

describe("lead schema matches the shared contract fixtures", () => {
  it("finds the fixtures", () => {
    expect(cases.length).toBeGreaterThanOrEqual(15);
  });

  it.each(cases)("$name", ({ fixture }) => {
    const result = schema.safeParse(fixture.fields);
    expect(result.success).toBe(fixture.expect.valid);
    if (!result.success) {
      expect(errorFields(result.error)).toEqual(fixture.expect.error_fields);
    }
  });

  it("lowercases and trims the email", () => {
    const result = schema.safeParse({
      name: "Ana",
      email: "  Ana@Example.COM ",
      country: "CO",
      program: "not-sure",
      career_goal: "Learn data",
      budget: "lt-500",
      availability: "lt-5h",
    });
    expect(result.success && result.data.email).toBe("ana@example.com");
  });
});
