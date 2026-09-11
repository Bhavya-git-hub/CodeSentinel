import { ApiKeyPanel } from "../components/ApiKeyPanel";
import "./Pages.css";

/**
 * Everything the browser holds for this instance, which is exactly one thing.
 *
 * A page rather than a modal on the scan form: the 401 message points here, and a
 * destination someone can be sent to, bookmark and come back to is worth more than a
 * dialog that has to be rediscovered each time the credential expires.
 */
export function SettingsPage() {
  return (
    <div className="page">
      <header className="page__head">
        <h1>Settings</h1>
        <p className="muted">
          This instance clones and analyses whatever it is pointed at, so its API is
          authenticated. A key is per browser and never leaves it.
        </p>
      </header>
      <ApiKeyPanel />
    </div>
  );
}
