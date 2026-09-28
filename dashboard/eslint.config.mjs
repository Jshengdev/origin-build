import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Stock shadcn/ui: never edited (SHADCN.md), so not linted.
    "components/ui/**",
    "hooks/use-mobile.ts",
    "storybook-static/**",
  ]),
]);

export default eslintConfig;
