import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

// Named, then exported — an anonymous `export default [...]` trips
// import/no-anonymous-default-export from next/core-web-vitals, and a warning
// nobody fixes is a warning everybody learns to scroll past.
const config = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
];

export default config;
