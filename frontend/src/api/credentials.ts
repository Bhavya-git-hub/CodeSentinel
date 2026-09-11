/**
 * Where the browser's API key lives, and what it honestly is.
 *
 * The deployment guide is blunt about this: a key in a browser bundle is not a secret,
 * because anyone who can load the page can read it. Two storage sites exist and they are
 * not equivalent, so this module keeps them apart rather than merging them into one
 * "the key" and letting the difference get lost:
 *
 * 1. `localStorage` — per viewer, typed in by the person using the page, never shipped.
 * 2. `VITE_CODESENTINEL_API_KEY` — baked in at build time and visible to every viewer.
 *
 * The second is acceptable only for a single-tenant internal deployment, and the UI says
 * so when it is in use. For anything else the right topology is a gateway that adds the
 * header server-side, with both of these unset.
 *
 * Every accessor here can throw: a private window, blocked site data, or an origin with
 * storage disabled all raise on plain `getItem`. A save that failed must report that it
 * failed -- a credential panel that says "saved" and then 401s on the next request is the
 * same lie as a scan that reports no findings because it never ran.
 */

export const API_KEY_STORAGE_KEY = "codesentinel.apiKey";

/** The build-time key, if the bundle was built with one. Visible to every viewer. */
export function bakedInKey(): string | undefined {
  return import.meta.env.VITE_CODESENTINEL_API_KEY || undefined;
}

/** The viewer's own key, or undefined if none is stored or storage is unreadable. */
export function storedKey(): string | undefined {
  try {
    return window.localStorage.getItem(API_KEY_STORAGE_KEY) || undefined;
  } catch {
    // Private windows and blocked site data both throw. Undefined is accurate: there is
    // no stored key available to this page, whatever the reason.
    return undefined;
  }
}

/**
 * The key requests are sent with.
 *
 * The viewer's own key wins over the baked-in one. A person who typed a key in did so to
 * override whatever the build shipped, and silently preferring the build's key would
 * make the panel's input look broken for the one reason nobody would guess.
 */
export function activeKey(): string | undefined {
  return storedKey() ?? bakedInKey();
}

/** Where the active key came from. The UI shows this; the three are not equivalent. */
export type KeySource = "stored" | "bundle" | "none";

export function keySource(): KeySource {
  if (storedKey() !== undefined) return "stored";
  if (bakedInKey() !== undefined) return "bundle";
  return "none";
}

/** Save the viewer's key. Returns false when storage refused, so the caller can say so. */
export function saveKey(key: string): boolean {
  try {
    window.localStorage.setItem(API_KEY_STORAGE_KEY, key);
    return true;
  } catch {
    return false;
  }
}

/** Forget the viewer's key. Returns false when storage refused. */
export function forgetKey(): boolean {
  try {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

/**
 * A key rendered for display: enough to recognise it, not enough to reuse it.
 *
 * Named keys are written `name:secret`, and the name is exactly the part that is safe to
 * show -- it is what the API logs, so a viewer comparing the panel against an operator's
 * logs needs to see it. The secret half is never displayed, in any length: a prefix on a
 * screen is a prefix in a screenshot.
 */
export function describeKey(key: string): string {
  const [name, separator] = [key.slice(0, key.indexOf(":")), key.includes(":")];
  return separator && name ? `${name}:…` : "…";
}
