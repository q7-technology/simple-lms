import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
  + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** A panel over the right of the screen. Escape or the dim closes it. Focus
 * moves in when it opens (to its first field, or with `focus="dialog"` to the
 * panel itself, for one whose first button does something that matters),
 * stays in while it is open, and goes back after. */
export function Drawer({ title, sub, onClose, children, focus = "first" }: {
  title: string; sub?: ReactNode; onClose: () => void; children: ReactNode; focus?: "first" | "dialog";
}) {
  const box = useRef<HTMLElement>(null);
  const heading = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const first = focus === "first"
      ? box.current?.querySelector(".dbody")?.querySelector<HTMLElement>(FOCUSABLE) : null;
    (first ?? box.current)?.focus();
    return () => { if (opener?.isConnected) opener.focus(); };
  }, []);

  function trap(e: ReactKeyboardEvent) {
    if (e.key !== "Tab" || !box.current) return;
    const all = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (all.length === 0) { e.preventDefault(); return; }
    const at = document.activeElement;
    if (e.shiftKey && (at === all[0] || at === box.current)) { e.preventDefault(); all.at(-1)!.focus(); }
    else if (!e.shiftKey && at === all.at(-1)) { e.preventDefault(); all[0].focus(); }
  }

  return (
    <>
      <div className="dim" onClick={onClose} />
      <aside ref={box} className="drawer" role="dialog" aria-modal="true" aria-labelledby={heading}
             tabIndex={-1} onKeyDown={trap}>
        <div className="dhead">
          <div className="flex-1 min-w-0">
            <h2 id={heading}>{title}</h2>
            {sub && <div className="small">{sub}</div>}
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="dbody">{children}</div>
      </aside>
    </>
  );
}

/** What went wrong, said plainly; nothing when nothing did. */
export function Problem({ error }: { error: string | null }) {
  return error ? <div className="msg r" role="alert">{error}</div> : null;
}
