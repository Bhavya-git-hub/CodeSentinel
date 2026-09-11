import { useState } from "react";
import type { FormEvent } from "react";

import {
  bakedInKey,
  describeKey,
  forgetKey,
  keySource,
  saveKey,
  storedKey,
} from "../api/credentials";
import "./ApiKeyPanel.css";

type Notice = { kind: "ok" | "error"; text: string } | null;

/**
 * Where a viewer sets the API key, replacing an instruction to type into the console.
 *
 * Three things this panel refuses to do, each because the alternative tells a
 * comfortable lie:
 *
 * **It never shows the secret back.** A configured key is shown as its name and an
 * ellipsis. The name is the half the API writes into its own logs, so it is what a
 * viewer needs in order to match the panel against what an operator can see; the secret
 * half on screen is the secret half in a screenshot.
 *
 * **It reports a save that did not happen.** `localStorage` throws in a private window
 * and where site data is blocked. A panel that said "saved" and then returned 401 on the
 * next request would send someone looking at the server for a fault in the browser.
 *
 * **It says when the key came from the bundle.** A build-time key is visible to everyone
 * who can load the page. Presenting that identically to a key the viewer typed in would
 * describe a published credential as a private one.
 */
export function ApiKeyPanel() {
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<Notice>(null);
  const [source, setSource] = useState(keySource);

  function handleSave(event: FormEvent) {
    event.preventDefault();
    const key = draft.trim();
    if (!key) return;
    if (saveKey(key)) {
      setDraft("");
      setSource(keySource());
      setNotice({ kind: "ok", text: "Key saved in this browser." });
    } else {
      setNotice({
        kind: "error",
        text:
          "This browser refused to store the key — private browsing, or site data is " +
          "blocked. Requests will go out without it.",
      });
    }
  }

  function handleForget() {
    if (forgetKey()) {
      setSource(keySource());
      setNotice({ kind: "ok", text: "Key removed from this browser." });
    } else {
      setNotice({ kind: "error", text: "This browser refused to clear the stored key." });
    }
  }

  const stored = storedKey();
  const baked = bakedInKey();

  return (
    <section className="keypanel">
      <h2>API key</h2>

      {source === "stored" && stored !== undefined ? (
        <p className="keypanel__state">
          Using a key stored in this browser: <span className="mono">{describeKey(stored)}</span>
          <button type="button" className="keypanel__forget" onClick={handleForget}>
            Forget it
          </button>
        </p>
      ) : null}

      {source === "bundle" && baked !== undefined ? (
        <p className="keypanel__state keypanel__state--warn">
          Using a key compiled into this page:{" "}
          <span className="mono">{describeKey(baked)}</span>. Anyone who can load this
          page can read it, so it is a shared credential rather than yours. A key you set
          below takes precedence over it.
        </p>
      ) : null}

      {source === "none" ? (
        <p className="keypanel__state muted">
          No key configured. If this instance requires one, requests will return 401.
        </p>
      ) : null}

      <form className="keypanel__form" onSubmit={handleSave}>
        <label htmlFor="api-key">
          {source === "none" ? "Set a key" : "Replace the key"}
        </label>
        <div className="keypanel__row">
          <input
            id="api-key"
            name="api-key"
            type="password"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="name:secret"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="submit" disabled={!draft.trim()}>
            Save
          </button>
        </div>
      </form>

      {notice ? (
        <p className={notice.kind === "ok" ? "keypanel__ok" : "error"} role="status">
          {notice.text}
        </p>
      ) : null}

      <p className="muted keypanel__note">
        Stored in this browser only &mdash; never sent anywhere but this API, and never
        included in a build. For a deployment with more than one operator, the better
        topology is a gateway that adds the header server-side, so the browser holds no
        credential at all.
      </p>
    </section>
  );
}
