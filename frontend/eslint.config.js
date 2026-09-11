import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // .vite is the dev server's dependency pre-bundle: generated third-party code that
  // appears the moment anyone runs `npm run dev`, and would otherwise make a local
  // `npm run lint` fail on React internals. CI never sees it, which is exactly why
  // it is worth ignoring here rather than discovering locally each time.
  { ignores: ["dist", "coverage", ".vite", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      "@typescript-eslint/no-non-null-assertion": "error",
      "@typescript-eslint/no-explicit-any": "error",
    },
  },
);
