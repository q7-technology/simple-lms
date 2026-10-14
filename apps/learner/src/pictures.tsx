/** A ticket's photos and a finger signature, as in the Simple TMS driver app. */
import { useEffect, useRef, useState, type RefObject } from "react";
import { forSending } from "./lib/picture";

/** A photo of the card (the phone offers its camera) or a PDF, made small on
 * the phone before it is kept. */
export function PhotoPicker({ label, hint, file, onFile }: {
  label: string; hint: string; file: Blob | null; onFile: (b: Blob | null) => void;
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
    try {
      onFile(await forSending(chosen));
    } catch {
      setError("That photo couldn't be read. Take it again.");
    }
  }

  return (
    <div className="pick">
      <label className="pickbox">
        {url && <img src={url} alt={label} />}
        <span><b>{file ? `${label}: added` : label}</b><small>{pdf ? "PDF added · tap to change" : file ? "Tap to take it again" : hint}</small></span>
        <input type="file" accept="image/*,application/pdf" className="sr-only"
               onChange={(e) => { void picked(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {error && <div className="msg r" role="alert">{error}</div>}
    </div>
  );
}

/** Sign here: a canvas signed with a finger. `onSigned` says whether
 * anything has been drawn. */
export function SignaturePad({ canvas, onSigned }: { canvas: RefObject<HTMLCanvasElement | null>; onSigned: (signed: boolean) => void }) {
  const drawing = useRef(false);
  // a drawing can't be read out, so say what it is for and whether it holds one
  const [hasInk, setHasInk] = useState(false);

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
    setHasInk(false);
    onSigned(false);
  }

  useEffect(() => {
    // as many pixels as the screen has, so the signature isn't blurred
    const el = canvas.current;
    if (!el) return;
    const ratio = window.devicePixelRatio || 1;
    el.width = Math.round(el.clientWidth * ratio) || 600;
    el.height = Math.round(el.clientHeight * ratio) || 300;
    const ctx = context();
    if (ctx) {
      ctx.scale(ratio, ratio);
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.strokeStyle = "#17202B";
    }
    clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function at(e: React.PointerEvent<HTMLCanvasElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
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
                const [x, y] = at(e);
                ctx.beginPath();
                ctx.moveTo(x, y);
              }}
              onPointerMove={(e) => {
                const ctx = context();
                if (!drawing.current || !ctx) return;
                const [x, y] = at(e);
                ctx.lineTo(x, y);
                ctx.stroke();
                setHasInk(true);
                onSigned(true);
              }}
              onPointerUp={() => { drawing.current = false; }}
              onPointerCancel={() => { drawing.current = false; }} />
      <span id="sign-how" className="sr-only">Sign with your finger (or the mouse).</span>
    </section>
  );
}
