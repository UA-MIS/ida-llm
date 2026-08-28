import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Frontend unit tests.
 *
 * ⚠ `make test-frontend` has always run `npm run test`, and until now this
 * package had no `test` script — so the target failed on the missing script
 * rather than running anything. It now runs these.
 *
 * `environment: node`: everything tested here is pure (branch logic, trust
 * rendering rules). Component rendering would need jsdom and a testing-library
 * dependency; the logic worth pinning was deliberately kept out of the
 * components so it can be tested without either. Mirrors apps/agile's setup.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
