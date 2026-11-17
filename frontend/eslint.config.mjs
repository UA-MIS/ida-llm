import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

// Named, then exported — an anonymous `export default [...]` trips
// import/no-anonymous-default-export from next/core-web-vitals, and a warning
// nobody fixes is a warning everybody learns to scroll past.
const config = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  // ⚠ THE ADMIN BOUNDARY (design §6.6). Public code may not import the admin
  // console, its auth, or its server-only API client. The admin tree itself is
  // exempt. `tests/admin-isolation.test.ts` enforces the same rule, so a
  // disabled lint rule cannot quietly open the door.
  {
    files: ["src/**/*.{ts,tsx}"],
    ignores: [
      "src/app/admin/**",
      "src/components/admin/**",
      "src/lib/admin/**",
      "src/auth.ts",
      "src/app/api/auth/**",
    ],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/lib/admin", "@/lib/admin/*", "@/components/admin", "@/components/admin/*", "@/auth"],
              message: "Public code must not import the admin console (design §6.6).",
            },
          ],
        },
      ],
    },
  },
];

export default config;
