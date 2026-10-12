import { useEffect, type ReactNode } from "react";

/** A panel over the right of the screen. Escape or the dim closes it. */
export function Drawer({ title, sub, onClose, children }: {
  title: string; sub?: ReactNode; onClose: () => void; children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <>
      <div className="dim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dhead">
          <div className="flex-1 min-w-0">
            <h2>{title}</h2>
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
