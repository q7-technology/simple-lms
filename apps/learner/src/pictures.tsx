/** A ticket's photos and a finger signature, as in the Simple TMS driver app. */
import { useEffect, useRef, useState, type RefObject } from "react";
import { forSending } from "./lib/picture";

/** The most a ticket's file may be, as the API has it (20 MB). A photo is
 * made small first; a PDF is sent as it is, so it is checked here. */
export const TICKET_MOST = 20_000_000;

/** A photo of the card (the phone offers its camera) or a PDF, made small on
 * the phone before it is kept. */
export function PhotoPicker({ label, hint, file, onFile, removable = false, pdf: takesPdf = true }: {
  label: string; hint: string; file: Blob | null; onFile: (b: Blob | null) => void;
  /** offer to take it away again (for a photo that is optional) */
  removable?: boolean;
  /** a PDF will do instead of a photo (a ticket's, not a sign-off's) */
  pdf?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pdf = file?.type === "application/pdf";
  useEffect(() => {
    if (!file || pdf) { setUrl(null); return; }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file, pdf]);

  async function picked(chosen: File | undefined) {
    if (!chosen) return;
    setError(null);
    if (!takesPdf && chosen.type === "application/pdf") { setError("Choose a photo, not a PDF."); return; }
    let ready: Blob;
    try {
      ready = await forSending(chosen);
    } catch {
      setError("That photo couldn't be read. Take it again.");
      return;
    }
    if (ready.size > TICKET_MOST) { setError("That file is too big: the most is 20 MB."); return; }
    onFile(ready);
  }

  return (
    <div className="pick">
      <label className="pickbox">
        {url && <img src={url} alt={label} />}
        <span><b>{file ? `${label}: added` : label}</b><small>{pdf ? "PDF added · tap to change" : file ? "Tap to take it again" : hint}</small></span>
        <input type="file" accept={takesPdf ? "image/*,application/pdf" : "image/*"} className="sr-only"
               onChange={(e) => { void picked(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {removable && file && (
        <button type="button" className="link" onClick={() => { setError(null); onFile(null); }}
                aria-label={`Remove the ${label.charAt(0).toLowerCase()}${label.slice(1)}`}>Remove</button>
      )}
      {error && <div className="msg r" role="alert">{error}</div>}
    </div>
  );
}

type Point = readonly [number, number];

/** How far a finger must travel, in CSS pixels, before the pad counts as
 * signed: a tap or a smudge is not a signature. */
export const ENOUGH_INK = 40;

/** The ink so far, plus one more piece of stroke. */
export function addInk(total: number, from: Point, to: Point): number {
  return total + Math.hypot(to[0] - from[0], to[1] - from[1]);
}

/** Sign here: a canvas signed with a finger. `onSigned` says whether enough
 * has been drawn to count as a signature. */
export function SignaturePad({ canvas, onSigned }: { canvas: RefObject<HTMLCanvasElement | null>; onSigned: (signed: boolean) => void }) {
  const drawing = useRef(false);
  const last = useRef<Point>([0, 0]);
  const ink = useRef(0);
  // a drawing can't be read out, so say what it is for and whether it holds one
  const [hasInk, setHasInk] = useState(false);
  const [turned, setTurned] = useState(false);

  function context(): CanvasRenderingContext2D | null {
    return canvas.current?.getContext("2d") ?? null;
  }

  function clear() {
    const el = canvas.current;
    const ctx = context();
    if (el && ctx) {
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, el.width, el.height);
    }
    ink.current = 0;
    setHasInk(false);
    setTurned(false);
    onSigned(false);
  }

  /** As many pixels as the screen has, so the signature isn't blurred. */
  function size(el: HTMLCanvasElement) {
    const ratio = window.devicePixelRatio || 1;
    return [Math.round(el.clientWidth * ratio) || 600, Math.round(el.clientHeight * ratio) || 300, ratio] as const;
  }

  function fit(el: HTMLCanvasElement) {
    const [width, height, ratio] = size(el);
    // a new size wipes the canvas and how it draws
    el.width = width;
    el.height = height;
    const ctx = context();
    if (ctx) {
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#17202B";
    }
  }

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    fit(el);
    clear();
    // the tablet turned or the window changed: a stretched drawing is no
    // signature, and strokes would land away from the finger, so start again
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(() => {
      const [width, height] = size(el);
      if (width === el.width && height === el.height) return;
      const had = ink.current > 0;
      drawing.current = false;
      fit(el);
      clear();
      setTurned(had);
    });
    watch.observe(el);
    return () => watch.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function at(e: React.PointerEvent<HTMLCanvasElement>): Point {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  return (
    <section aria-label="Signature" className="padbox">
      <div className="padhead">
        <span>Sign here</span>
        <button type="button" className="link" onClick={clear} aria-label="Clear the signature">Clear</button>
      </div>
      <canvas ref={canvas} className="pad" role="img" aria-describedby="sign-how"
              aria-label={hasInk ? "Signature pad: signed" : "Signature pad: empty"}
              onPointerDown={(e) => {
                const ctx = context();
                if (!ctx) return;
                e.currentTarget.setPointerCapture?.(e.pointerId);
                drawing.current = true;
                setTurned(false);
                const [x, y] = last.current = at(e);
                ctx.beginPath();
                ctx.moveTo(x, y);
              }}
              onPointerMove={(e) => {
                const ctx = context();
                if (!drawing.current || !ctx) return;
                const point = at(e);
                ctx.lineTo(point[0], point[1]);
                ctx.stroke();
                ink.current = addInk(ink.current, last.current, point);
                last.current = point;
                if (!hasInk && ink.current >= ENOUGH_INK) {
                  setHasInk(true);
                  onSigned(true);
                }
              }}
              onPointerUp={() => { drawing.current = false; }}
              onPointerCancel={() => { drawing.current = false; }} />
      {turned && <div className="small" role="status" style={{ color: "var(--color-ink-2)" }}>Sign again: the screen turned.</div>}
      <span id="sign-how" className="sr-only">Sign with your finger (or the mouse).</span>
    </section>
  );
}
