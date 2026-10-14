import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Policy } from "../api/types";
import { useSession } from "../auth/Session";
import { toBlob } from "../lib/picture";
import { SignaturePad } from "../pictures";
import { Back, plain } from "../ui";

/** Read the policy, then type your name and sign with a finger. */
export function SignPolicy() {
  const { key = "" } = useParams();
  const { person } = useSession();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [signed, setSigned] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const canvas = useRef<HTMLCanvasElement>(null);

  const load = useCallback(async () => {
    setTrouble(null);
    try {
      setPolicy(await api.get<Policy>(`/v1/policies/${encodeURIComponent(key)}`));
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404
        ? "There's nothing to sign here yet. Ask your manager." : plain(e));
    }
  }, [key]);

  useEffect(() => { void load(); }, [load]);

  async function sign(e: FormEvent) {
    e.preventDefault();
    if (!policy || !canvas.current) return;
    setBusy(true);
    setError(null);
    try {
      const signature = await api.upload("signature", await toBlob(canvas.current, "image/png"));
      await api.post(`/v1/policies/${encodeURIComponent(key)}/sign`, {
        version: policy.version.version, signed_name: name.trim(), signature: signature.id,
      });
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "new_version") {
        // the ink was for the old text: the pad starts again with the new version
        setSigned(false);
        setError("The policy has changed: read the new version and sign again.");
        await load();
      } else if (err instanceof ApiError && err.code === "already_signed") {
        setDone(true);
      } else {
        setError(plain(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (done && policy) {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Signed">
          <b>Ding!</b>
          <span>You've signed {policy.name}, version {policy.version.version}.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </main>
    );
  }

  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!policy && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {policy && (
        <>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{policy.name}</h1>
          <div className="small" style={{ color: "var(--color-muted)" }}>Version {policy.version.version}
            {policy.version.note && <> · What changed: {policy.version.note}</>}</div>
          <article className="policy" aria-label="The policy">{policy.version.body}</article>
          <form onSubmit={sign} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div className="label">
              <label htmlFor="signed-name">Type your name</label>
              {/* the API takes the name on their record, case and spacing aside */}
              {person && <span id="signed-name-hint" className="small" style={{ fontWeight: 400, color: "var(--color-muted)" }}>
                Type your name as it is on your record: {person.name}</span>}
              <input id="signed-name" className="input" autoComplete="off" value={name} onChange={(e) => setName(e.target.value)}
                     placeholder={person?.name} aria-describedby={person ? "signed-name-hint" : undefined} required />
            </div>
            <SignaturePad key={policy.version.id} canvas={canvas} onSigned={setSigned} />
            <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>
              Signing says you have read this policy and will follow it.</p>
            {error && <div className="msg r" role="alert">{error}</div>}
            <button type="submit" className="big primary" disabled={busy || !signed || !name.trim()}>Sign</button>
          </form>
        </>
      )}
    </main>
  );
}
