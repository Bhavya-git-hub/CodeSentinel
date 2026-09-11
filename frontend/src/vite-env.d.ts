/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "1" selects the bundled fixtures instead of the live API. Never a fallback. */
  readonly VITE_CODESENTINEL_DEMO?: string;
  readonly VITE_CODESENTINEL_API_BASE?: string;
  /** Baked into the bundle and therefore visible to every viewer. Prefer a
   *  gateway that adds the header server-side, or localStorage per viewer. */
  readonly VITE_CODESENTINEL_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
