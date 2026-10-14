import { useEffect, useState } from "react";
import { api } from "../api/client";

/** A ticket's photo or a signature, kept by the API. An <img> can't send the
 * session's token, so the bytes are fetched with it and shown from a blob:
 * URL, let go when it is gone. A PDF is offered to save instead. */
export function Picture({ upload, label, width = 240 }: { upload: string; label: string; width?: number }) {
  const [file, setFile] = useState<{ url: string; pdf: boolean } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    api.blob(`/v1/uploads/${encodeURIComponent(upload)}`)
      .then((b) => {
        if (!live) return;
        made = URL.createObjectURL(b);
        setFile({ url: made, pdf: b.type === "application/pdf" });
      })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [upload]);
  if (failed) return <span className="small">{label} couldn't be loaded.</span>;
  if (!file) return <span className="small">Loading {label.toLowerCase()}…</span>;
  if (file.pdf) return <a className="btn" href={file.url} download={`${label}.pdf`}>Save {label.toLowerCase()} (PDF)</a>;
  return <img src={file.url} alt={label} width={width} style={{ borderRadius: 10, display: "block", border: "1px solid var(--color-line)" }} />;
}
