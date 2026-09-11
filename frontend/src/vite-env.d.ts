/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" selects the bundled fixtures instead of the live API. Never a fallback. */
  readonly VITE_CODESENTINEL_DEMO?: string;
  readonly VITE_CODESENTINEL_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
