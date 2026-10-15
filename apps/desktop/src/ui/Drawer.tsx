import {
  createContext, useCallback, useContext, useEffect, useId, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type ReactNode,
} from "react";

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
  + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** What would be lost by closing, by whatever in the drawer says so. */
const Guard = createContext<((id: string, why: string | null) => void) | null>(null);

/** Something in a drawer that closing would lose (`why`, a sentence), or
 * null for nothing: while there is, closing it asks first. */
export function useCloseGuard(why: string | null) {
  const set = useContext(Guard);
  const id = useId();
  useEffect(() => {
    set?.(id, why);
    return () => set?.(id, null);
  }, [set, id, why]);
}

/** A panel over the right of the screen. Escape or the dim closes it. Focus
 * moves in when it opens (to its first field, or with `focus="dialog"` to the
 * panel itself, for one whose first button does something that matters),
 * stays in while it is open, and goes back after. Closing on something not
 * yet saved (see useCloseGuard) asks first. */
export function Drawer({ title, sub, onClose, children, focus = "first" }: {
  title: string; sub?: ReactNode; onClose: () => void; children: ReactNode; focus?: "first" | "dialog";
}) {
  const box = useRef<HTMLElement>(null);
  const heading = useId();
  const guards = useRef(new Map<string, string>());
  const guard = useCallback((id: string, why: string | null) => {
    if (why) guards.current.set(id, why);
    else guards.current.delete(id);
  }, []);
  // what closing would lose, while asking whether to anyway
  const [asking, setAsking] = useState<string | null>(null);
  const close = useCallback(() => {
    const why = [...guards.current.values()][0];
    if (why) setAsking(why);
    else onClose();
  }, [onClose]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (asking) setAsking(null);
      else close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close, asking]);
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
      <div className="dim" onClick={close} />
      <aside ref={box} className="drawer" role="dialog" aria-modal="true" aria-labelledby={heading}
             tabIndex={-1} onKeyDown={trap}>
        <div className="dhead">
          <div className="flex-1 min-w-0">
            <h2 id={heading}>{title}</h2>
            {sub && <div className="small">{sub}</div>}
          </div>
          <button type="button" className="btn" onClick={close} aria-label="Close">✕</button>
        </div>
        <div className="dbody">
          {asking && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm"><b>{asking} Close it anyway?</b></span>
              <button type="button" className="btn danger" onClick={onClose}>Close anyway</button>
              <button type="button" className="btn" autoFocus onClick={() => setAsking(null)}>Keep editing</button>
            </div>
          )}
          <Guard.Provider value={guard}>{children}</Guard.Provider>
        </div>
      </aside>
    </>
  );
}

/** What went wrong, said plainly; nothing when nothing did. */
export function Problem({ error }: { error: string | null }) {
  return error ? <div className="msg r" role="alert">{error}</div> : null;
}
