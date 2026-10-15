import { useState } from "react";

/** A secret or a key Simple LMS shows this once and keeps no copy of (or,
 * for a webhook's secret, never shows again). `onDone` puts it away. */
export function ShownOnce({ label, value, why, onDone }: {
  label: string; value: string; why: string; onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch { /* no clipboard here: it can still be selected and copied */ }
  }
  return (
    <div className="card flex flex-col gap-2" role="status">
      <label className="label">{label}
        <input className="field font-mono" value={value} readOnly onFocus={(e) => e.target.select()} />
      </label>
      <div className="small">{why} Copy it now: Simple LMS won't show it again.</div>
      <div className="flex gap-2">
        <button type="button" className="btn" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" className="btn primary" onClick={onDone}>Done</button>
      </div>
    </div>
  );
}
