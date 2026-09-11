# CodeSentinel Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A landing page and a working risk dashboard for CodeSentinel, in which *measured*, *genuinely zero* and *unknown* are three visually distinct states rather than one.

**Architecture:** React + TypeScript on Vite. A three-module data layer (`client` / `demo` / `source`) selects its source by environment variable and never falls back between them. Presentation primitives (`Measured`, `Unknown`) own the null-versus-zero rule so no page can get it wrong locally.

**Tech Stack:** React 18, TypeScript 5, Vite 5, React Router 6, Vitest, Testing Library. Plain CSS custom properties — no Tailwind, no component kit, no data-fetching library.

**Spec:** [docs/superpowers/specs/2026-09-11-frontend-design.md](../specs/2026-09-11-frontend-design.md) — read it before starting; this plan argues from it.

## Global Constraints

Copy these exactly; every task inherits them.

- **Run from `frontend/`.** `npm run dev` · `npm run build` · `npm run test` · `npm run lint`.
- **The gate:** `npm run lint` · `npx tsc --noEmit` · `npm run test -- --run` · `npm run build`. All four must pass before any commit.
- **TypeScript `strict`.** No `any`. No non-null assertions (`!`) on API data — the whole point is that values are legitimately absent.
- **Phosphor (`--phosphor`) is only ever applied to a value the system measured.** It is never decoration, never a hover colour, never a border on something unmeasured.
- **`null` never renders as `0` and never renders as an empty cell.** It renders through the `Unknown` primitive, as the literal token `None`.
- **Unknown is `--unknown` slate plus hatch. Never `--halt`, never amber.** Amber means caution, which is a claim about the file we have not earned.
- **Mono (`--font-mono`) for values the system measured; sans (`--font-sans`) for words we wrote.**
- **No fallback between data sources.** If the live client throws, the error surfaces. `source.ts` must never catch an error and return fixtures.
- **Copy:** sentence case, active voice, no exclamation marks. Errors say what happened and what to do. Buttons name the action that occurs.
- **Commits:** conventional subject (`feat(frontend):`, `test(frontend):`, `chore:`), plus a body explaining what would have been wrong otherwise.

---

### Task 1: Scaffold, tokens and fonts

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/.env.example`, `frontend/eslint.config.js`
- Create: `frontend/src/main.tsx`, `frontend/src/styles/tokens.css`, `frontend/src/styles/base.css`
- Create: `frontend/src/vite-env.d.ts`

**Interfaces:**
- Produces: a running dev server on port 5173; the CSS custom properties every later task uses; `import.meta.env.VITE_CODESENTINEL_DEMO` typed.

- [ ] **Step 1: Create the package manifest**

`frontend/package.json`:

```json
{
  "name": "codesentinel-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "test": "vitest"
  },
  "dependencies": {
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "react-router-dom": "6.28.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/react": "16.1.0",
    "@testing-library/user-event": "14.5.2",
    "@types/react": "18.3.12",
    "@types/react-dom": "18.3.1",
    "@vitejs/plugin-react": "4.3.4",
    "eslint": "9.17.0",
    "globals": "15.14.0",
    "jsdom": "25.0.1",
    "typescript": "5.7.2",
    "typescript-eslint": "8.18.1",
    "vite": "5.4.11",
    "vitest": "2.1.8"
  }
}
```

Versions are pinned exactly, with no `^`. ADR 0008 keeps the backend's dependencies
resolvable rather than locked, but a frontend has a lockfile by default and pinned
versions make it honest about what was actually built.

- [ ] **Step 2: Create the TypeScript and Vite configuration**

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedIndexedAccess": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`noUncheckedIndexedAccess` is on deliberately: this UI indexes into arrays of API data,
and the setting forces the absent case to be handled rather than assumed.

`frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // The backend's cors_origins already defaults to http://localhost:5173, but
      // proxying keeps the browser same-origin in development so a CORS
      // misconfiguration cannot masquerade as an API outage.
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
```

- [ ] **Step 3: Create `index.html` with the fonts**

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CodeSentinel</title>
    <meta
      name="description"
      content="Rank a repository's files by complexity and recency-weighted churn, and say plainly what could not be measured."
    />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Gabarito:wght@500;600;700&family=Geist:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create the design tokens**

`frontend/src/styles/tokens.css`:

```css
/*
 * Single-theme by decision, not omission. Phosphor encodes measurement: the amount of
 * green on screen is a readout of how much of a repository was actually analysed. On a
 * light ground that signal does not survive, so there is no light variant.
 */
:root {
  color-scheme: dark;

  --void: #04080a;
  --panel: #0a1014;
  --panel-lift: #111a20;
  --rule: #17232b;

  /* Applied only to a value the system determined. Never decoration. */
  --phosphor: #4ade80;
  --phosphor-dim: #2a6f4a;
  --phosphor-glow: rgba(74, 222, 128, 0.14);

  /* Could not be determined. Desaturated on purpose: unknown is an absence of
     signal, not a warning. Amber here would claim something about the file. */
  --unknown: #6b7a8f;
  --unknown-fill: rgba(107, 122, 143, 0.1);

  --halt: #e86a5c;
  --halt-fill: rgba(232, 106, 92, 0.12);

  --bone: #e8edf0;
  --mute: #8a97a5;
  --faint: #566370;

  --font-display: "Gabarito", "Geist", system-ui, sans-serif;
  --font-sans: "Geist", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SF Mono", Consolas, monospace;

  --step--1: 0.8125rem;
  --step-0: 1rem;
  --step-1: 1.25rem;
  --step-2: 1.625rem;
  --step-3: 2.25rem;
  --step-4: clamp(2.5rem, 6vw, 4rem);

  --gap-xs: 6px;
  --gap-s: 12px;
  --gap-m: 20px;
  --gap-l: 36px;
  --gap-xl: 64px;

  --radius: 4px;
  --edge: 1px solid var(--rule);
}
```

- [ ] **Step 5: Create the base stylesheet**

`frontend/src/styles/base.css`:

```css
@import "./tokens.css";

*,
*::before,
*::after {
  box-sizing: border-box;
}

html {
  -webkit-text-size-adjust: 100%;
}

body {
  margin: 0;
  background: var(--void);
  color: var(--bone);
  font-family: var(--font-sans);
  font-size: var(--step-0);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

h1,
h2,
h3 {
  font-family: var(--font-display);
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: -0.02em;
  margin: 0;
  text-wrap: balance;
}

p {
  margin: 0;
  max-width: 68ch;
}

a {
  color: inherit;
}

:focus-visible {
  outline: 2px solid var(--phosphor);
  outline-offset: 2px;
}

button {
  font: inherit;
  cursor: pointer;
}

/* The hatch that marks an unmeasured value. Defined once so every surface that has
   to show absence shows the same absence. */
.hatch {
  background-image: repeating-linear-gradient(
    45deg,
    transparent,
    transparent 3px,
    var(--unknown-fill) 3px,
    var(--unknown-fill) 6px
  );
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 6: Create the environment declarations and entry point**

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" selects the bundled fixtures instead of the live API. Never a fallback. */
  readonly VITE_CODESENTINEL_DEMO?: string;
  readonly VITE_CODESENTINEL_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

`frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import "./styles/base.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("No #root element. index.html and main.tsx have diverged.");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
```

`frontend/.env.example`:

```
# Serve the bundled fixtures instead of the live API. The UI announces demo mode
# loudly whenever this is set; it is never selected automatically.
VITE_CODESENTINEL_DEMO=1

# Where the API lives. Leave unset in development: vite proxies /api to :8000.
# VITE_CODESENTINEL_API_BASE=http://localhost:8000
```

- [ ] **Step 7: Create the ESLint config and test setup**

`frontend/eslint.config.js`:

```js
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage"] },
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
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 8: Create a placeholder App so the build succeeds**

`frontend/src/App.tsx`:

```tsx
export function App() {
  return <main>CodeSentinel</main>;
}
```

- [ ] **Step 9: Install and verify**

Run: `cd frontend && npm install && npm run lint && npx tsc --noEmit && npm run build`
Expected: all four succeed.

- [ ] **Step 10: Commit**

```bash
git add frontend/
git commit -m "chore(frontend): scaffold vite, react and the design tokens"
```

Body: explain that the palette is single-theme by decision because phosphor encodes
measurement and does not survive a light ground, and that `noUncheckedIndexedAccess` is on
because this UI indexes into arrays of API data where absence is real.

---

### Task 2: API types and the non-falling-back data source

The load-bearing task. A reviewer could accept everything else and reject this.

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/demo.ts`, `frontend/src/api/source.ts`
- Test: `frontend/src/api/source.test.ts`

**Interfaces:**
- Produces:
  - `type ScanStatus = "pending" | "running" | "succeeded" | "partial" | "failed"`
  - `interface ScanDetail`, `interface FileRisk`, `interface RiskQueue`, `interface ScanAccepted`
  - `interface DataSource { submitScan(url: string): Promise<ScanAccepted>; getScan(id: string): Promise<ScanDetail>; getMetrics(id: string): Promise<RiskQueue>; listScans(): Promise<ScanDetail[]>; }`
  - `const source: DataSource`, `const IS_DEMO: boolean`
  - `class ApiError extends Error { status: number; detail: string }`

- [ ] **Step 1: Write the failing test**

`frontend/src/api/source.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ApiError } from "./client";
import { demoSource } from "./demo";
import { selectSource } from "./source";

describe("selectSource", () => {
  it("serves fixtures only when demo mode is explicitly set", () => {
    expect(selectSource({ demo: "1" }, demoSource, liveStub())).toBe(demoSource);
  });

  it("serves the live client by default", () => {
    const live = liveStub();
    expect(selectSource({}, demoSource, live)).toBe(live);
  });

  it("does not treat an arbitrary value as demo mode", () => {
    const live = liveStub();
    expect(selectSource({ demo: "0" }, demoSource, live)).toBe(live);
    expect(selectSource({ demo: "false" }, demoSource, live)).toBe(live);
  });

  it("never falls back to fixtures when the live client fails", async () => {
    const failing = liveStub(() => {
      throw new ApiError(503, "database unavailable");
    });
    const selected = selectSource({}, demoSource, failing);

    await expect(selected.getScan("any-id")).rejects.toBeInstanceOf(ApiError);
  });
});

function liveStub(onCall?: () => never) {
  const boom = () => {
    if (onCall) onCall();
    return Promise.reject(new Error("not stubbed"));
  };
  return {
    submitScan: boom,
    getScan: boom,
    getMetrics: boom,
    listScans: boom,
  } as unknown as ReturnType<typeof demoSourceType>;
}

declare function demoSourceType(): typeof demoSource;
```

Simplify the stub helper if TypeScript objects — the assertions are what matter. The
fourth test is the one that must never be deleted: a UI that silently serves fixtures
when the backend is down is the confident-report-about-nothing failure the backend
spends five phases preventing.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- --run src/api/source.test.ts`
Expected: FAIL — the modules do not exist.

- [ ] **Step 3: Write the types**

`frontend/src/api/types.ts`:

```ts
/**
 * The API contract, as settled by phases 3 and 4 and proved by CI run 34587978470.
 *
 * Every `| null` here is deliberate and load-bearing. The backend distinguishes a value
 * it measured, a value that is genuinely zero, and a value it could not determine; the
 * types carry that distinction so a component cannot quietly collapse it.
 */

export type ScanStatus = "pending" | "running" | "succeeded" | "partial" | "failed";

export const TERMINAL_STATUSES: readonly ScanStatus[] = ["succeeded", "partial", "failed"];

export interface ScanAccepted {
  scan_id: string;
  status: ScanStatus;
}

export interface ScanDetail {
  scan_id: string;
  status: ScanStatus;
  /** Null until the clone resolves the ref. */
  commit_sha: string | null;
  /** Populated for a failed scan, phrased for a person to act on. */
  error: string | null;
  file_count: number;
  commit_count: number;
  started_at: string;
  completed_at: string | null;
}

export interface FileRisk {
  path: string;
  is_test: boolean;
  /** Null means the lines could not be counted, not that the file is empty. */
  loc: number | null;
  cyclomatic_complexity: number | null;
  maintainability_index: number | null;
  /** 0 means it never changed in the mined history. Null means every change was binary. */
  churn_score: number | null;
  normalized_complexity: number | null;
  normalized_churn: number | null;
  /** Null when either component is unknown. Never zero in that case. */
  risk_score: number | null;
}

export interface RiskQueue {
  scan_id: string;
  status: ScanStatus;
  total_files: number;
  /** How many files carry no risk score. Part of the contract, not a footnote. */
  unmeasured: number;
  analyzer_statuses: Record<string, { status?: string; error?: string }>;
  files: FileRisk[];
}

export interface DataSource {
  submitScan(url: string): Promise<ScanAccepted>;
  getScan(id: string): Promise<ScanDetail>;
  getMetrics(id: string): Promise<RiskQueue>;
  listScans(): Promise<ScanDetail[]>;
}
```

- [ ] **Step 4: Write the live client**

`frontend/src/api/client.ts`:

```ts
import type {
  DataSource,
  RiskQueue,
  ScanAccepted,
  ScanDetail,
} from "./types";

const BASE = import.meta.env.VITE_CODESENTINEL_API_BASE ?? "";

/**
 * A failed request, carrying the reason the API gave.
 *
 * The backend phrases its refusals for a person -- "The transport 'ext' is not
 * permitted. Allowed transports: https." -- so the detail is preserved verbatim and
 * shown. Paraphrasing it into "Invalid URL" would throw away the only part that tells
 * someone what to do next.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (cause) {
    // The network never reached the API. Distinguished from an API that answered,
    // because "the server is down" and "the server refused this" need different
    // actions from the reader.
    throw new ApiError(0, `Could not reach the API at ${BASE || "this origin"}.`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join("; ");
      }
    }
  } catch {
    // Body was not JSON. The status line below is all we honestly have.
  }
  return `The API returned ${response.status} with no explanation.`;
}

export const liveSource: DataSource = {
  submitScan: (url) =>
    request<ScanAccepted>("/api/v1/scans", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  getScan: (id) => request<ScanDetail>(`/api/v1/scans/${id}`),
  getMetrics: (id) => request<RiskQueue>(`/api/v1/scans/${id}/metrics`),
  // The API has no list endpoint yet. Returning an empty list rather than inventing
  // one keeps the dashboard honest: it shows the scans this browser started.
  listScans: () => Promise.resolve([]),
};
```

- [ ] **Step 5: Write the fixtures**

`frontend/src/api/demo.ts`:

```ts
import type { DataSource, FileRisk, RiskQueue, ScanDetail } from "./types";

/**
 * Fixtures carrying real measurements.
 *
 * These are the figures the shipped services actually produced against this repository:
 * 44 files inventoried under backend/app, 39 non-merge commits, churn from the real
 * `churn_score` over the real history. Complexity is null throughout because Radon
 * genuinely could not run without a Docker daemon -- so even the sample data tells the
 * truth about itself, and demo mode demonstrates the unknown state rather than hiding it.
 */

const MEASURED: ReadonlyArray<[string, number, number, number]> = [
  ["backend/app/services/sandbox/runner.py", 433, 433.1, 1.0],
  ["backend/app/services/ingestion/cloner.py", 328, 328.0, 0.757],
  ["backend/app/services/ingestion/history.py", 239, 239.0, 0.552],
  ["backend/app/services/ingestion/pipeline.py", 195, 209.0, 0.483],
  ["backend/app/services/analyzers/analysis.py", 175, 175.0, 0.404],
  ["backend/app/api/v1/scans.py", 165, 171.0, 0.395],
  ["backend/app/services/analyzers/radon.py", 170, 170.0, 0.393],
  ["backend/app/config.py", 151, 158.4, 0.366],
  ["backend/app/models/code.py", 159, 158.3, 0.365],
  ["backend/app/services/ingestion/inventory.py", 152, 152.0, 0.351],
  ["backend/app/models/history.py", 136, 135.5, 0.313],
  ["backend/app/services/scoring/risk.py", 98, 98.0, 0.226],
  ["backend/app/services/mining/churn.py", 84, 84.0, 0.194],
  ["backend/app/services/ingestion/url.py", 78, 78.0, 0.180],
  ["backend/app/models/base.py", 62, 71.0, 0.164],
  ["backend/app/db.py", 61, 64.0, 0.148],
];

const DEMO_SCAN_ID = "3f7c1a90-4d2b-4c11-9d8e-2a6f5b0c7e41";

const files: FileRisk[] = MEASURED.map(([path, loc, churn, normalizedChurn]) => ({
  path,
  is_test: path.includes("/tests/"),
  loc,
  // Radon did not run: unknown, not zero. This is what the UI must render as `None`.
  cyclomatic_complexity: null,
  maintainability_index: null,
  churn_score: churn,
  normalized_complexity: null,
  normalized_churn: normalizedChurn,
  risk_score: null,
}));

const scan: ScanDetail = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  commit_sha: "3c5ad571f0e2b8a94c6d1e7f2a8b5c3d9e0f4a16",
  error: null,
  file_count: 44,
  commit_count: 39,
  started_at: "2026-09-11T10:03:13Z",
  completed_at: "2026-09-11T10:03:58Z",
};

const queue: RiskQueue = {
  scan_id: DEMO_SCAN_ID,
  status: "partial",
  total_files: 44,
  unmeasured: 44,
  analyzer_statuses: {
    radon: {
      status: "partial",
      error: "Radon could not run in the sandbox: no Docker daemon is reachable.",
    },
  },
  files,
};

export const DEMO_SCAN = DEMO_SCAN_ID;

export const demoSource: DataSource = {
  submitScan: () => Promise.resolve({ scan_id: DEMO_SCAN_ID, status: "pending" }),
  getScan: () => Promise.resolve(scan),
  getMetrics: () => Promise.resolve(queue),
  listScans: () => Promise.resolve([scan]),
};
```

- [ ] **Step 6: Write the source selector**

`frontend/src/api/source.ts`:

```ts
import { liveSource } from "./client";
import { demoSource } from "./demo";
import type { DataSource } from "./types";

/**
 * Chooses the data source. It does not arbitrate between them at runtime.
 *
 * There is deliberately no try/catch around the live client that returns fixtures on
 * failure. That fallback is the obvious convenience and it is the one thing this file
 * exists to prevent: a UI that invents data when the backend is unreachable produces a
 * confident report about a repository nobody analysed, which is the exact failure the
 * backend spends five phases avoiding.
 *
 * Demo mode is configuration, like the backend's clone_allowed_protocols -- explicit,
 * announced in the interface, and impossible to reach by accident (anti-pattern #1).
 */
export function selectSource(
  env: { demo?: string | undefined },
  demo: DataSource,
  live: DataSource,
): DataSource {
  return env.demo === "1" ? demo : live;
}

export const IS_DEMO = import.meta.env.VITE_CODESENTINEL_DEMO === "1";

export const source: DataSource = selectSource(
  { demo: import.meta.env.VITE_CODESENTINEL_DEMO },
  demoSource,
  liveSource,
);
```

- [ ] **Step 7: Run the tests**

Run: `cd frontend && npm run test -- --run src/api/source.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/
git commit -m "feat(frontend): add the API types and a data source that never falls back"
```

Body must state plainly that `source.ts` has no fallback path, why one would be
catastrophic in this product specifically, and that the fixtures carry real measurements
including a genuine null complexity.

---

### Task 3: The Measured and Unknown primitives

The rule lives here so no page can get it wrong locally.

**Files:**
- Create: `frontend/src/components/Value.tsx`, `frontend/src/components/Value.css`
- Test: `frontend/src/components/Value.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `<Metric value={number | null} digits?: number unit?: string />`
  - `<Bar value={number | null} label?: string />` — normalised 0–1 magnitude
  - `<StatusPill status={ScanStatus} />`

- [ ] **Step 1: Write the failing test**

`frontend/src/components/Value.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Bar, Metric } from "./Value";

describe("Metric", () => {
  it("renders a measured value", () => {
    render(<Metric value={433.1} digits={1} />);
    expect(screen.getByText("433.1")).toBeInTheDocument();
  });

  it("renders a genuine zero as zero", () => {
    render(<Metric value={0} digits={1} />);
    expect(screen.getByText("0.0")).toBeInTheDocument();
  });

  it("renders an unknown value as None, never as zero", () => {
    render(<Metric value={null} />);
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("marks an unknown value for assistive technology", () => {
    render(<Metric value={null} />);
    expect(screen.getByText("None")).toHaveAttribute(
      "title",
      "Could not be determined",
    );
  });

  it("distinguishes a zero from an unknown in the DOM", () => {
    const { container: zero } = render(<Metric value={0} />);
    const { container: unknown } = render(<Metric value={null} />);
    expect(zero.querySelector(".value--unknown")).toBeNull();
    expect(unknown.querySelector(".value--unknown")).not.toBeNull();
  });
});

describe("Bar", () => {
  it("draws nothing but hatch for an unknown magnitude", () => {
    const { container } = render(<Bar value={null} />);
    expect(container.querySelector(".bar__fill")).toBeNull();
    expect(container.querySelector(".hatch")).not.toBeNull();
  });

  it("draws a fill proportional to a measured magnitude", () => {
    const { container } = render(<Bar value={0.5} />);
    const fill = container.querySelector<HTMLElement>(".bar__fill");
    expect(fill?.style.width).toBe("50%");
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- --run src/components/Value.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`frontend/src/components/Value.tsx`:

```tsx
import type { ScanStatus } from "../api/types";
import "./Value.css";

/**
 * The one place that decides how an absent number looks.
 *
 * Every metric in this product is nullable on purpose (ADR 0004): a file Radon could not
 * parse is not a file of complexity zero, and a binary-only history is not a file that
 * never changed. Rendering null as 0 -- or as a blank cell, which reads as zero -- would
 * discard that at the last possible moment, after five phases of backend work spent
 * preserving it. So pages never format a number themselves; they pass it here.
 */
export function Metric({
  value,
  digits = 0,
  unit,
}: {
  value: number | null;
  digits?: number;
  unit?: string;
}) {
  if (value === null) {
    return (
      <span className="value value--unknown" title="Could not be determined">
        None
      </span>
    );
  }
  return (
    <span className="value value--measured">
      {value.toFixed(digits)}
      {unit ? <span className="value__unit">{unit}</span> : null}
    </span>
  );
}

/**
 * A magnitude on a 0-1 scale.
 *
 * An unknown magnitude is hatch with no fill, so the row still occupies its place in the
 * queue and is visibly not a low score. A zero-length fill would be indistinguishable
 * from a measured zero.
 */
export function Bar({ value, label }: { value: number | null; label?: string }) {
  if (value === null) {
    return (
      <div className="bar" role="img" aria-label={label ?? "Could not be determined"}>
        <div className="bar__track hatch" />
      </div>
    );
  }
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className="bar"
      role="img"
      aria-label={label ?? `${pct.toFixed(0)} percent of the maximum`}
    >
      <div className="bar__track">
        <div className="bar__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

const STATUS_COPY: Record<ScanStatus, string> = {
  pending: "Queued",
  running: "Running",
  succeeded: "Complete",
  partial: "Partial",
  failed: "Failed",
};

/**
 * Partial is styled as its own state, not as a milder success.
 *
 * It means something specific here: the scan produced usable work and knows what it
 * could not determine. Showing it as a success would hide the gap; showing it as a
 * failure would throw the usable half away.
 */
export function StatusPill({ status }: { status: ScanStatus }) {
  return (
    <span className={`pill pill--${status}`}>
      <span className="pill__dot" aria-hidden="true" />
      {STATUS_COPY[status]}
    </span>
  );
}
```

`frontend/src/components/Value.css`:

```css
.value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--step--1);
}

.value--measured {
  color: var(--phosphor);
}

.value--unknown {
  color: var(--unknown);
  border-bottom: 1px dashed var(--unknown);
  cursor: help;
}

.value__unit {
  color: var(--faint);
  margin-left: 2px;
}

.bar {
  min-width: 96px;
}

.bar__track {
  position: relative;
  height: 16px;
  border: 1px solid var(--rule);
  border-radius: 2px;
  overflow: hidden;
  background: var(--void);
}

.bar__fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, var(--phosphor-dim), var(--phosphor));
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-xs);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 3px 9px;
  border-radius: 2px;
  border: 1px solid currentColor;
  white-space: nowrap;
}

.pill__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.pill--pending,
.pill--running {
  color: var(--mute);
}

.pill--running .pill__dot {
  animation: pulse 1.4s ease-in-out infinite;
}

.pill--succeeded {
  color: var(--phosphor);
}

.pill--partial {
  color: var(--unknown);
}

.pill--failed {
  color: var(--halt);
}

@keyframes pulse {
  50% {
    opacity: 0.25;
  }
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm run test -- --run src/components/Value.test.tsx`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/
git commit -m "feat(frontend): add the measured and unknown value primitives"
```

Body: explain that centralising the rule is what stops a page from formatting a null
itself, and that a blank cell reads as zero to a person, so unknown has to be a token.

---

### Task 4: App shell, navigation and the demo banner

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/Shell.tsx`, `frontend/src/components/Shell.css`
- Test: `frontend/src/components/Shell.test.tsx`

**Interfaces:**
- Consumes: `IS_DEMO` from `../api/source`.
- Produces: `<Shell>` wrapping routed content; routes `/`, `/scans`, `/scans/:id`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/Shell.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DemoBanner } from "./Shell";

describe("DemoBanner", () => {
  it("announces demo mode when fixtures are the source", () => {
    render(
      <MemoryRouter>
        <DemoBanner isDemo={true} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/sample data/i);
  });

  it("renders nothing when the live API is the source", () => {
    const { container } = render(
      <MemoryRouter>
        <DemoBanner isDemo={false} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- --run src/components/Shell.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the shell**

`frontend/src/components/Shell.tsx`:

```tsx
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import "./Shell.css";

/**
 * Says, permanently and without being dismissible, that the figures on screen are
 * samples.
 *
 * Not a toast and not a one-time notice: the whole product is a claim about a real
 * repository, so a reader who arrives mid-page must still be able to tell that these
 * numbers describe nothing they own.
 */
export function DemoBanner({ isDemo }: { isDemo: boolean }) {
  if (!isDemo) return null;
  return (
    <div className="demo" role="status">
      Showing sample data from CodeSentinel&rsquo;s own repository. Nothing here was
      scanned just now.
    </div>
  );
}

export function Shell({ isDemo, children }: { isDemo: boolean; children: ReactNode }) {
  return (
    <>
      <DemoBanner isDemo={isDemo} />
      <header className="masthead">
        <NavLink to="/" className="wordmark">
          <span className="wordmark__mark" aria-hidden="true" />
          CodeSentinel
        </NavLink>
        <nav className="nav">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/scans">Scans</NavLink>
        </nav>
      </header>
      <main>{children}</main>
      <footer className="footer">
        Ranks files by complexity and recency-weighted churn. Says plainly what it could
        not measure.
      </footer>
    </>
  );
}
```

`frontend/src/components/Shell.css`:

```css
.demo {
  background: var(--unknown-fill);
  border-bottom: 1px solid var(--unknown);
  color: var(--bone);
  font-size: var(--step--1);
  padding: 10px var(--gap-m);
  text-align: center;
}

.masthead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-m);
  padding: var(--gap-m);
  border-bottom: var(--edge);
  flex-wrap: wrap;
}

.wordmark {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-s);
  font-family: var(--font-display);
  font-weight: 700;
  font-size: var(--step-1);
  letter-spacing: -0.02em;
  text-decoration: none;
}

.wordmark__mark {
  width: 9px;
  height: 9px;
  background: var(--phosphor);
  box-shadow: 0 0 12px var(--phosphor-glow);
}

.nav {
  display: flex;
  gap: var(--gap-m);
  font-size: var(--step--1);
}

.nav a {
  color: var(--mute);
  text-decoration: none;
  padding-bottom: 2px;
  border-bottom: 1px solid transparent;
}

.nav a:hover {
  color: var(--bone);
}

.nav a.active {
  color: var(--bone);
  border-bottom-color: var(--phosphor);
}

.footer {
  border-top: var(--edge);
  margin-top: var(--gap-xl);
  padding: var(--gap-m);
  color: var(--faint);
  font-size: var(--step--1);
}
```

- [ ] **Step 4: Wire the routes**

`frontend/src/App.tsx`:

```tsx
import { Route, Routes } from "react-router-dom";

import { IS_DEMO } from "./api/source";
import { Shell } from "./components/Shell";
import { Landing } from "./pages/Landing";
import { ScanDetailPage } from "./pages/ScanDetailPage";
import { ScansPage } from "./pages/ScansPage";

export function App() {
  return (
    <Shell isDemo={IS_DEMO}>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/scans" element={<ScansPage />} />
        <Route path="/scans/:id" element={<ScanDetailPage />} />
      </Routes>
    </Shell>
  );
}
```

Tasks 5 and 6 create those three pages. Create empty stubs now so the build passes, and
fill them in there.

- [ ] **Step 5: Run the tests and the build**

Run: `cd frontend && npm run test -- --run && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): add the app shell and a permanent demo notice"
```

Body: explain why the demo notice is permanent and undismissible rather than a toast.

---

### Task 5: The risk queue table and scan detail

**Files:**
- Create: `frontend/src/components/RiskTable.tsx`, `frontend/src/components/RiskTable.css`
- Create: `frontend/src/pages/ScanDetailPage.tsx`, `frontend/src/hooks/useScan.ts`
- Test: `frontend/src/components/RiskTable.test.tsx`

**Interfaces:**
- Consumes: `FileRisk`, `RiskQueue` from `../api/types`; `Metric`, `Bar` from `./Value`.
- Produces: `<RiskTable queue={RiskQueue} />`; `sortFiles(files, key): FileRisk[]`;
  `usePolledScan(id): { scan, queue, error, loading }`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/RiskTable.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FileRisk } from "../api/types";
import { RiskTable, sortFiles } from "./RiskTable";

function file(path: string, risk: number | null): FileRisk {
  return {
    path,
    is_test: false,
    loc: 10,
    cyclomatic_complexity: risk === null ? null : 5,
    maintainability_index: null,
    churn_score: 1,
    normalized_complexity: risk,
    normalized_churn: risk,
    risk_score: risk,
  };
}

describe("sortFiles", () => {
  it("ranks higher risk first", () => {
    const sorted = sortFiles([file("low", 0.1), file("high", 0.9)], "risk_score");
    expect(sorted.map((f) => f.path)).toEqual(["high", "low"]);
  });

  it("sorts unknown risk last, never first", () => {
    const sorted = sortFiles(
      [file("unknown", null), file("high", 0.9), file("low", 0.1)],
      "risk_score",
    );
    expect(sorted.map((f) => f.path)).toEqual(["high", "low", "unknown"]);
  });

  it("keeps unknown last even when every other file scores zero", () => {
    const sorted = sortFiles([file("unknown", null), file("zero", 0)], "risk_score");
    expect(sorted.map((f) => f.path)).toEqual(["zero", "unknown"]);
  });
});

describe("RiskTable", () => {
  const queue = {
    scan_id: "abc",
    status: "partial" as const,
    total_files: 3,
    unmeasured: 1,
    analyzer_statuses: { radon: { status: "partial", error: "no daemon" } },
    files: [file("a.py", 0.5), file("b.py", null)],
  };

  it("states how many files could not be measured", () => {
    render(<RiskTable queue={queue} />);
    expect(screen.getByText(/1 of 3 files could not be ranked/i)).toBeInTheDocument();
  });

  it("shows the analyser's reason rather than hiding it", () => {
    render(<RiskTable queue={queue} />);
    expect(screen.getByText(/no daemon/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- --run src/components/RiskTable.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the table**

`frontend/src/components/RiskTable.tsx`:

```tsx
import type { FileRisk, RiskQueue } from "../api/types";
import { Bar, Metric } from "./Value";
import "./RiskTable.css";

export type SortKey = "risk_score" | "churn_score" | "cyclomatic_complexity" | "loc";

/**
 * Ranks files, keeping unmeasurable ones at the bottom.
 *
 * Mirrors the database index, which is DESC NULLS LAST. An unknown is not a low score --
 * a file Radon could not parse may be the worst in the repository -- but it must not
 * outrank a file that was actually measured and found dangerous. Last, and visibly
 * unknown, is the only honest position for it.
 */
export function sortFiles(files: FileRisk[], key: SortKey): FileRisk[] {
  return [...files].sort((a, b) => {
    const left = a[key];
    const right = b[key];
    if (left === null && right === null) return a.path.localeCompare(b.path);
    if (left === null) return 1;
    if (right === null) return -1;
    return right - left;
  });
}

export function RiskTable({ queue }: { queue: RiskQueue }) {
  const files = sortFiles(queue.files, "risk_score");
  const reasons = Object.entries(queue.analyzer_statuses);

  return (
    <section className="queue">
      <div className="queue__head">
        <h2>Review queue</h2>
        {queue.unmeasured > 0 ? (
          <p className="queue__caveat">
            {queue.unmeasured} of {queue.total_files} files could not be ranked. They are
            listed last, and they are unknown rather than safe.
          </p>
        ) : (
          <p className="queue__caveat">
            All {queue.total_files} files were measured and ranked.
          </p>
        )}
        {reasons.map(([name, detail]) => (
          <p key={name} className="queue__reason">
            <span className="queue__analyzer">{name}</span>
            {detail.error ?? "reported no detail"}
          </p>
        ))}
      </div>

      <div className="queue__scroll">
        <table className="queue__table">
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Lines</th>
              <th scope="col">Complexity</th>
              <th scope="col">Churn</th>
              <th scope="col">Weighting</th>
              <th scope="col">Risk</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr
                key={file.path}
                className={file.risk_score === null ? "row--unknown" : undefined}
              >
                <th scope="row">
                  <span className="path">{file.path}</span>
                  {file.is_test ? <span className="tag">test</span> : null}
                </th>
                <td>
                  <Metric value={file.loc} />
                </td>
                <td>
                  <Metric value={file.cyclomatic_complexity} digits={1} />
                </td>
                <td>
                  <Metric value={file.churn_score} digits={1} />
                </td>
                <td>
                  <Bar
                    value={file.normalized_churn}
                    label={`churn weighting for ${file.path}`}
                  />
                </td>
                <td>
                  <Metric value={file.risk_score} digits={3} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

`frontend/src/components/RiskTable.css`:

```css
.queue {
  display: flex;
  flex-direction: column;
  gap: var(--gap-m);
}

.queue__head {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
}

.queue__caveat {
  color: var(--mute);
  font-size: var(--step--1);
}

.queue__reason {
  font-family: var(--font-mono);
  font-size: var(--step--1);
  color: var(--unknown);
  display: flex;
  gap: var(--gap-s);
  flex-wrap: wrap;
}

.queue__analyzer {
  color: var(--faint);
}

.queue__scroll {
  overflow-x: auto;
  border: var(--edge);
  border-radius: var(--radius);
}

.queue__table {
  width: 100%;
  border-collapse: collapse;
  background: var(--panel);
}

.queue__table th,
.queue__table td {
  text-align: left;
  padding: 9px var(--gap-s);
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}

.queue__table thead th {
  background: var(--panel-lift);
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 500;
  color: var(--mute);
  letter-spacing: 0.02em;
}

.queue__table tbody tr:last-child td,
.queue__table tbody tr:last-child th {
  border-bottom: none;
}

/* An unmeasured row is dimmed, not hidden and not coloured as a warning. */
.row--unknown th,
.row--unknown td {
  background: var(--unknown-fill);
}

.path {
  font-family: var(--font-mono);
  font-size: var(--step--1);
  font-weight: 400;
  color: var(--bone);
}

.tag {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--faint);
  border: 1px solid var(--rule);
  border-radius: 2px;
  padding: 1px 4px;
  margin-left: var(--gap-s);
}
```

- [ ] **Step 4: Implement the polling hook**

`frontend/src/hooks/useScan.ts`:

```ts
import { useEffect, useState } from "react";

import { source } from "../api/source";
import { TERMINAL_STATUSES } from "../api/types";
import type { RiskQueue, ScanDetail } from "../api/types";

const POLL_MS = 2000;

/**
 * Follows one scan until it reaches a terminal status.
 *
 * Analysis is asynchronous by constraint C2, so the browser polls rather than waiting on
 * a request. Polling stops on a terminal status -- an interval that keeps running after
 * a scan has finished is a request every two seconds, forever, for a row that cannot
 * change.
 */
export function usePolledScan(id: string | undefined) {
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [queue, setQueue] = useState<RiskQueue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    let timer: number | undefined;

    async function tick() {
      if (!id) return;
      try {
        const detail = await source.getScan(id);
        if (cancelled) return;
        setScan(detail);

        if (TERMINAL_STATUSES.includes(detail.status)) {
          const metrics = await source.getMetrics(id);
          if (cancelled) return;
          setQueue(metrics);
        } else {
          timer = window.setTimeout(tick, POLL_MS);
        }
      } catch (cause) {
        if (cancelled) return;
        // Surfaced, never swallowed into an empty table: an empty queue and an
        // unreachable API must not look the same.
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [id]);

  return { scan, queue, error, loading };
}
```

- [ ] **Step 5: Implement the scan detail page**

`frontend/src/pages/ScanDetailPage.tsx`:

```tsx
import { useParams } from "react-router-dom";

import { RiskTable } from "../components/RiskTable";
import { StatusPill } from "../components/Value";
import { usePolledScan } from "../hooks/useScan";
import "./Pages.css";

export function ScanDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { scan, queue, error, loading } = usePolledScan(id);

  if (error) {
    return (
      <div className="page">
        <h1>This scan could not be loaded</h1>
        <p className="error">{error}</p>
      </div>
    );
  }

  if (loading || !scan) {
    return (
      <div className="page">
        <p className="muted">Loading scan&hellip;</p>
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__head">
        <div className="page__title">
          <h1>Scan</h1>
          <StatusPill status={scan.status} />
        </div>
        <dl className="facts">
          <div>
            <dt>Commit</dt>
            <dd className="mono">{scan.commit_sha?.slice(0, 12) ?? "not resolved"}</dd>
          </div>
          <div>
            <dt>Files</dt>
            <dd className="mono">{scan.file_count}</dd>
          </div>
          <div>
            <dt>Commits mined</dt>
            <dd className="mono">{scan.commit_count}</dd>
          </div>
        </dl>
      </header>

      {scan.error ? <p className="error">{scan.error}</p> : null}
      {queue ? <RiskTable queue={queue} /> : <p className="muted">Waiting for results.</p>}
    </div>
  );
}
```

- [ ] **Step 6: Run the tests**

Run: `cd frontend && npm run test -- --run`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): add the risk queue table and scan detail"
```

Body: explain that `sortFiles` mirrors the database's `DESC NULLS LAST` and why an
unknown must sort last without being treated as a low score, and that polling stops at a
terminal status.

---

### Task 6: The landing page and the scans page

**Files:**
- Create: `frontend/src/pages/Landing.tsx`, `frontend/src/pages/ScansPage.tsx`, `frontend/src/pages/Pages.css`
- Test: `frontend/src/pages/ScansPage.test.tsx`

**Interfaces:**
- Consumes: `source`, `ApiError`, `RiskTable`, `Metric`.
- Produces: the two routed pages.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/ScansPage.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { SubmitForm } from "./ScansPage";

describe("SubmitForm", () => {
  it("shows the API's own refusal verbatim", async () => {
    const submit = vi
      .fn()
      .mockRejectedValue(
        new Error("The transport 'ext' is not permitted. Allowed transports: https."),
      );

    render(
      <MemoryRouter>
        <SubmitForm onSubmit={submit} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/repository url/i), "ext::sh -c whoami");
    await userEvent.click(screen.getByRole("button", { name: /start scan/i }));

    expect(
      await screen.findByText(/the transport 'ext' is not permitted/i),
    ).toBeInTheDocument();
  });

  it("does not submit an empty url", async () => {
    const submit = vi.fn();
    render(
      <MemoryRouter>
        <SubmitForm onSubmit={submit} />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: /start scan/i }));
    expect(submit).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- --run src/pages/ScansPage.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the scans page**

`frontend/src/pages/ScansPage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { source } from "../api/source";
import "./Pages.css";

/**
 * The URL field submits to the API without pre-validating the transport.
 *
 * The backend already refuses a hostile URL at its boundary and phrases the refusal for
 * a person -- "The transport 'ext' is not permitted. Allowed transports: https." A
 * second copy of that rule in the browser would be a second thing to keep in step, and
 * the browser's copy is the one an attacker skips anyway.
 */
export function SubmitForm({
  onSubmit,
}: {
  onSubmit: (url: string) => Promise<{ scan_id: string }>;
}) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function handle(event: React.FormEvent) {
    event.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await onSubmit(url.trim());
      navigate(`/scans/${accepted.scan_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="submit" onSubmit={handle}>
      <label htmlFor="repo-url">Repository URL</label>
      <div className="submit__row">
        <input
          id="repo-url"
          name="repo-url"
          type="text"
          placeholder="https://github.com/psf/requests"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" disabled={busy}>
          {busy ? "Starting…" : "Start scan"}
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
    </form>
  );
}

export function ScansPage() {
  return (
    <div className="page">
      <header className="page__head">
        <h1>Scan a repository</h1>
        <p className="muted">
          Public repositories only, over https. The clone is size- and time-bounded, runs
          under a hardened git, and is deleted when the scan ends.
        </p>
      </header>
      <SubmitForm onSubmit={(url) => source.submitScan(url)} />
    </div>
  );
}
```

- [ ] **Step 4: Implement the landing page**

`frontend/src/pages/Landing.tsx`:

```tsx
import { Link } from "react-router-dom";

import { DEMO_SCAN, demoSource } from "../api/demo";
import { Bar, Metric } from "../components/Value";
import "./Pages.css";

/**
 * The hero is the product's most characteristic object: a ranked queue in which some
 * cells say None.
 *
 * A headline statistic with a gradient would be the default treatment and would say
 * nothing only this product can say. The queue does: it shows both that files are ranked
 * and that the ranking admits what it does not know.
 */
export function Landing() {
  const preview = demoSource;
  void preview;

  const rows = [
    { path: "services/sandbox/runner.py", churn: 433.1, weight: 1.0 },
    { path: "services/ingestion/cloner.py", churn: 328.0, weight: 0.757 },
    { path: "services/ingestion/history.py", churn: 239.0, weight: 0.552 },
    { path: "services/ingestion/pipeline.py", churn: 209.0, weight: 0.483 },
    { path: "services/analyzers/analysis.py", churn: 175.0, weight: 0.404 },
  ];

  return (
    <div className="page">
      <section className="hero">
        <h1>Read the dangerous code first.</h1>
        <p className="hero__lede">
          CodeSentinel ranks a repository&rsquo;s files by complexity multiplied by
          recency-weighted churn &mdash; and tells you which files it could not measure,
          instead of scoring them zero.
        </p>

        <div className="hero__queue" aria-label="Example review queue">
          <div className="hero__queue-head">
            <span>File</span>
            <span>Churn</span>
            <span>Weighting</span>
            <span>Risk</span>
          </div>
          {rows.map((row) => (
            <div className="hero__row" key={row.path}>
              <span className="path">{row.path}</span>
              <Metric value={row.churn} digits={1} />
              <Bar value={row.weight} label={`weighting for ${row.path}`} />
              <Metric value={null} />
            </div>
          ))}
          <p className="hero__note">
            Every risk score here reads <span className="mono">None</span>. Radon had no
            container to run in, so complexity is unknown &mdash; and an unknown component
            gives an unknown product, not a zero.
          </p>
        </div>

        <Link className="cta" to="/scans">
          Scan a repository
        </Link>
      </section>

      <section className="strip">
        <article>
          <h2>Complexity alone ranks badly.</h2>
          <p>
            Intricate code nobody touches is not where defects land. Churn alone is no
            better: a heavily edited trivial file is not worth a reviewer&rsquo;s morning.
            The product of the two is the claim.
          </p>
        </article>
        <article>
          <h2>Recency is the whole point.</h2>
          <p>
            Churn decays on a 90-day half-life. Total lifetime churn would put a file
            rewritten five years ago above one being rewritten this week, which is exactly
            backwards for deciding what to read.
          </p>
        </article>
        <article>
          <h2>Absence is reported, not filled in.</h2>
          <p>
            A file the parser could not read is not a simple file. A binary-only history is
            not a file that never changed. Both are recorded as unknown, and they sort last
            rather than looking safe.
          </p>
        </article>
      </section>

      <section className="strip">
        <article>
          <h2>Untrusted code stays in a box.</h2>
          <p>
            Every analyser runs in a container with no network, a read-only mount, dropped
            capabilities and a non-root user. There is no argument that relaxes it.
          </p>
        </article>
        <article>
          <h2>Results carry their own provenance.</h2>
          <p>
            Each scan stores the commit it read, the tool versions that read it, and the
            configuration in force. A number you cannot reproduce is a number you cannot
            act on.
          </p>
        </article>
        <article>
          <h2>See it on a real repository.</h2>
          <p>
            The queue above is CodeSentinel measured against itself: 44 files, 39 commits,
            real churn.{" "}
            <Link to={`/scans/${DEMO_SCAN}`}>Open the full scan</Link>.
          </p>
        </article>
      </section>
    </div>
  );
}
```

Remove the unused `preview` lines when implementing; they are there only to show the
import shape. Import only what the file uses, or `npm run lint` will fail.

- [ ] **Step 5: Write the page stylesheet**

`frontend/src/pages/Pages.css`:

```css
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: var(--gap-l) var(--gap-m);
  display: flex;
  flex-direction: column;
  gap: var(--gap-xl);
}

.page__head {
  display: flex;
  flex-direction: column;
  gap: var(--gap-s);
}

.page__title {
  display: flex;
  align-items: center;
  gap: var(--gap-s);
  flex-wrap: wrap;
}

.hero {
  display: flex;
  flex-direction: column;
  gap: var(--gap-m);
  padding-top: var(--gap-l);
}

.hero h1 {
  font-size: var(--step-4);
  max-width: 18ch;
}

.hero__lede {
  font-size: var(--step-1);
  color: var(--mute);
  max-width: 60ch;
}

.hero__queue {
  border: var(--edge);
  border-radius: var(--radius);
  background: var(--panel);
  overflow-x: auto;
}

.hero__queue-head,
.hero__row {
  display: grid;
  grid-template-columns: minmax(220px, 2fr) 90px 120px 90px;
  gap: var(--gap-s);
  align-items: center;
  padding: 10px var(--gap-s);
  border-bottom: 1px solid var(--rule);
}

.hero__queue-head {
  background: var(--panel-lift);
  font-size: 11px;
  color: var(--mute);
}

.hero__note {
  padding: var(--gap-s);
  color: var(--mute);
  font-size: var(--step--1);
}

.cta {
  align-self: flex-start;
  font-family: var(--font-mono);
  font-size: var(--step--1);
  text-decoration: none;
  color: var(--void);
  background: var(--phosphor);
  padding: 10px 18px;
  border-radius: var(--radius);
}

.cta:hover {
  background: var(--bone);
}

.strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--gap-l);
}

.strip h2 {
  font-size: var(--step-1);
  margin-bottom: var(--gap-xs);
}

.strip p {
  color: var(--mute);
}

.facts {
  display: flex;
  gap: var(--gap-l);
  flex-wrap: wrap;
  margin: 0;
}

.facts dt {
  font-size: 11px;
  color: var(--faint);
}

.facts dd {
  margin: 0;
}

.mono {
  font-family: var(--font-mono);
  font-size: var(--step--1);
}

.muted {
  color: var(--mute);
}

.error {
  color: var(--halt);
  background: var(--halt-fill);
  border-left: 2px solid var(--halt);
  padding: var(--gap-s);
  font-family: var(--font-mono);
  font-size: var(--step--1);
}

.submit {
  display: flex;
  flex-direction: column;
  gap: var(--gap-xs);
  max-width: 620px;
}

.submit label {
  font-size: var(--step--1);
  color: var(--mute);
}

.submit__row {
  display: flex;
  gap: var(--gap-s);
  flex-wrap: wrap;
}

.submit input {
  flex: 1 1 320px;
  background: var(--panel);
  border: var(--edge);
  border-radius: var(--radius);
  color: var(--bone);
  font-family: var(--font-mono);
  font-size: var(--step--1);
  padding: 10px var(--gap-s);
}

.submit button {
  background: var(--phosphor);
  color: var(--void);
  border: none;
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: var(--step--1);
  padding: 10px 18px;
}

.submit button:disabled {
  background: var(--faint);
  cursor: not-allowed;
}

@media (max-width: 600px) {
  .hero__queue-head,
  .hero__row {
    grid-template-columns: minmax(160px, 2fr) 70px 90px 70px;
  }
}
```

- [ ] **Step 6: Run the full gate**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run && npm run build`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): add the landing page and scan submission"
```

Body: explain why the hero is a queue rather than a headline statistic, and why the
browser does not duplicate the backend's URL validation.

---

### Task 7: Compose, CI and the records

**Files:**
- Create: `frontend/Dockerfile`, `frontend/.dockerignore`
- Modify: `docker-compose.yml`, `.github/workflows/ci.yml`, `README.md`
- Create: `docs/sprints/frontend-dashboard.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a `frontend` compose service and a CI job that lints, type-checks, tests and builds it.

- [ ] **Step 1: Add the frontend CI job**

In `.github/workflows/ci.yml`, add a job alongside the existing ones:

```yaml
  frontend:
    name: Frontend
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - run: npm ci
      - run: npm run lint
      - run: npx tsc --noEmit
      # --run, never watch mode: vitest defaults to watching, which in CI is a job
      # that hangs until the runner times out rather than a job that fails.
      - run: npm run test -- --run
      - run: npm run build
```

- [ ] **Step 2: Add the compose service**

In `docker-compose.yml`, after `worker`:

```yaml
  frontend:
    build:
      context: ./frontend
    environment:
      # Unset: the browser talks to the API through the same origin in the compose
      # stack. Demo mode is deliberately NOT enabled here -- a running stack has a real
      # API, and serving fixtures beside it would be the fallback this design forbids.
      VITE_CODESENTINEL_API_BASE: ""
    ports:
      - "5173:80"
    depends_on:
      api:
        condition: service_healthy
```

- [ ] **Step 3: Add the Dockerfile**

`frontend/Dockerfile`:

```dockerfile
# Build the static bundle, then serve it. Two stages so the runtime image carries no
# node_modules and no toolchain.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Single-page app: unknown paths must return index.html, or a refresh on /scans/<id>
# would 404 against a route that only exists in the browser.
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  location / {\n    try_files $uri $uri/ /index.html;\n  }\n}\n' > /etc/nginx/conf.d/default.conf
```

`frontend/.dockerignore`:

```
node_modules
dist
.env
.env.local
coverage
```

- [ ] **Step 4: Update the README**

Replace the Status section's last paragraph and add a frontend section documenting
`npm install`, `npm run dev`, and that `VITE_CODESENTINEL_DEMO=1` serves fixtures and says
so on screen.

- [ ] **Step 5: Write the record**

`docs/sprints/frontend-dashboard.md`, following the existing sprint records: scope
delivered, an acceptance table citing the CI run number, and obligations on phase 5
(findings and coverage must reuse the `Measured` / `Unknown` primitives rather than
inventing a second treatment for absence).

Do not fill in the acceptance table until CI has actually run.

- [ ] **Step 6: Run the whole gate and commit**

```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run test -- --run && npm run build
git add frontend/ docker-compose.yml .github/ README.md docs/
git commit -m "ci(frontend): build, lint and test the frontend; add compose service"
```

---

## Verification before calling the frontend done

- [ ] `npm run lint`, `npx tsc --noEmit`, `npm run test -- --run` and `npm run build` all pass.
- [ ] `VITE_CODESENTINEL_DEMO=1 npm run dev` shows the banner and the queue full of `None`.
- [ ] `npm run dev` without the variable, and with no API running, shows an error — **not** fixtures. This is the one manual check that proves the no-fallback rule.
- [ ] The page is usable at 400px wide with no horizontal body scroll.
- [ ] Keyboard focus is visible on every control; `prefers-reduced-motion` is respected.
- [ ] CI is green and the sprint record cites the run number.
