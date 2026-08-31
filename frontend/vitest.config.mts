import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Frontend unit tests.
 *
 * ⚠ `make test-frontend` has always run `npm run test`, and until now this
 * package had no `test` script — so the target failed on the missing script
 * rather than running anything. It now runs these.
 *
 * ⚠ TWO ENVIRONMENTS, SPLIT BY FILENAME. The default stays `node`, because the
 * rule this suite was built on still holds: the logic worth pinning is kept OUT
 * of the components, in pure modules, so most of it needs no DOM. `lib/specimen`
 * is the newest example — every rule that stops the landing page inventing a
 * finding is a pure function with its own test file.
 *
 * `*.dom.test.tsx` opts into jsdom. That exists for exactly one class of claim
 * a pure test cannot make: that the rendered PAGE shows the honest empty states
 * rather than merely computing them. A landing page that quietly dropped its
 * "not measured yet" rows would pass every pure test in this directory.
 */
const alias = { "@": fileURLToPath(new URL("./src", import.meta.url)) };

export default defineConfig({
  test: {
    // ⚠ TWO PROJECTS, NOT `environmentMatchGlobs`. That option is deprecated in
    // vitest 3 and printed a warning on every run; `projects` is its
    // replacement and expresses the same split -- one suite per environment,
    // selected by filename -- without the notice. The BEHAVIOUR is unchanged:
    // `*.dom.test.tsx` gets jsdom, everything else gets node.
    //
    // Each project carries its own `resolve`/`esbuild`: a project is a config in
    // its own right and does NOT inherit the root's, so dropping either here
    // breaks the `@/` alias or the JSX transform for that half of the suite.
    projects: [
      {
        resolve: { alias },
        esbuild: { jsx: "automatic" },
        test: {
          name: "node",
          environment: "node",
          include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
          exclude: ["tests/**/*.dom.test.tsx"],
        },
      },
      {
        resolve: { alias },
        esbuild: { jsx: "automatic" },
        test: {
          name: "dom",
          environment: "jsdom",
          include: ["tests/**/*.dom.test.tsx"],
        },
      },
    ],
  },
  resolve: { alias },
  // ⚠ REQUIRED FOR THE .tsx TESTS. tsconfig sets `"jsx": "preserve"` because
  // Next does its own JSX transform at build time — which leaves esbuild here
  // defaulting to the CLASSIC runtime and failing with "React is not defined"
  // the moment a component is rendered. Next never sees this setting; it only
  // governs how vitest transforms the same files.
  esbuild: { jsx: "automatic" },
});
