# ADR 0010: Pydantic is the source of the contracts: JSON Schema to Zod

Status: accepted

## Context

The agent (Python) and the web app (TypeScript) share the workspace schema and the API shapes. Hand-written
copies drift, and the dashboard validates every agent response.

## Decision

Pydantic models are the single source of truth. `python -m lead_qualifier.scripts.export_schemas` writes JSON
Schemas and the OpenAPI document to `packages/contracts`, and `pnpm contracts:generate` turns them into Zod
schemas and TypeScript types. CI regenerates and fails on drift. The dynamic lead form schema is the one
exception: it is built twice (`domain/lead_form.py` and `apps/web/lib/forms/build-lead-schema.ts`) and both are
tested against the same fixtures in `packages/contracts/fixtures/lead-submissions`.

## Consequences

- A change to a model shows up as a generated diff on both sides and in the contract tests.
- Generated files are committed and reviewed, and the generator toolchain is part of the build.
- The dynamic form validator is duplicated on purpose and kept honest only by the shared fixtures.

## Alternatives considered

- OpenAPI codegen for the client only: the workspace schema would still be written twice.
- A TypeScript-first schema (Zod as source): the agent would need a reverse generator.
