import type { ScanStatus } from "../api/types";
import "./Value.css";

/**
 * The one place that decides how an absent number looks.
 *
 * Every metric in this product is nullable on purpose (ADR 0004): a file Radon could not
 * parse is not a file of complexity zero, and a binary-only history is not a file that
 * never changed. Rendering null as 0 -- or as a blank cell, which reads as zero to a
 * person -- would discard that at the last possible moment, after five phases of backend
 * work spent preserving it. So pages never format a number themselves; they pass it here.
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
 * An unknown magnitude is hatch with no fill, so the row still holds its place and is
 * visibly not a low score. A zero-length fill would be indistinguishable from a measured
 * zero, which is the confusion this whole design exists to prevent.
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
 * could not determine. Showing it as success would hide the gap; showing it as failure
 * would throw the usable half away.
 */
export function StatusPill({ status }: { status: ScanStatus }) {
  return (
    <span className={`pill pill--${status}`}>
      <span className="pill__dot" aria-hidden="true" />
      {STATUS_COPY[status]}
    </span>
  );
}
