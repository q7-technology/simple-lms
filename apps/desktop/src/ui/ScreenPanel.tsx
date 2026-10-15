import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { noteDrawerClosed } from "./focusReturn";
import { screenTitle } from "./screens";

/** Is this Escape someone else's? A drawer open in the screen closes
 * first, and a field being typed in keeps it, so nothing half done is lost. */
export function escapeBelongsElsewhere(target: EventTarget | null): boolean {
  if (document.querySelector('[aria-modal="true"]')) return true;
  return target instanceof HTMLInputElement || target instanceof HTMLSelectElement
    || target instanceof HTMLTextAreaElement || (target instanceof HTMLElement && target.isContentEditable);
}

/** A screen over the classroom, as every panel is over Simple WMS's map.
 * Escape, the dim or ✕ goes back to the classroom. Not modal: the bar along the top
 * stays one click away, the matrix with it. */
export function ScreenPanel({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const title = screenTitle(pathname);
  const close = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || escapeBelongsElsewhere(e.target)) return;
      navigate("/");
    };
    // on the document, so it hears Escape before a drawer inside (on the window) closes
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate]);

  // keyboard users start in the drawer; the classroom takes focus back on close.
  // Before any effect inside: a screen that opens with its own drawer (People
  // at ?person=) then takes focus from here, and gives it back here on close.
  useLayoutEffect(() => {
    close.current?.focus();
    return () => noteDrawerClosed();
  }, []);

  return (
    <>
      <div className="screendim" aria-hidden="true" onClick={() => navigate("/")} />
      <section className="screenpanel" aria-label={title}>
        <div className="screenbar">
          <Link ref={close} to="/" className="btn" aria-label="Back to the classroom" title="Back to the classroom (Esc)">✕</Link>
          <span className="small"><Link to="/">Classroom</Link> / <b>{title}</b></span>
        </div>
        <div className="screenbody">{children}</div>
      </section>
    </>
  );
}
