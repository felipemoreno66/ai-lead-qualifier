import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// Each test builds its own auth instance from the env it stubs.
afterEach(() => {
  delete (globalThis as { __leadqAuth?: unknown }).__leadqAuth;
});
