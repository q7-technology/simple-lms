import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Ticket, Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { PhotoPicker } from "../pictures";
import { Back, plain } from "../ui";

/** A photo of the front and back, the number and the expiry. It waits for a
 * manager's check. */
export function AddTicket() {
  const { key = "" } = useParams();
  const { person } = useSession();
  const [item, setItem] = useState<TrainingItem | null>(null);
  const [sentBack, setSentBack] = useState<string | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [front, setFront] = useState<Blob | null>(null);
  const [back, setBack] = useState<Blob | null>(null);
  const [number, setNumber] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    const code = encodeURIComponent(person!.code);
    Promise.all([api.get<Training>(`/v1/people/${code}/training`), api.get<Ticket[]>(`/v1/people/${code}/tickets`)])
      .then(([training, tickets]) => {
        const found = training.items.find((i) => i.key === key);
        if (!found || found.kind !== "ticket") { setTrouble("That ticket isn't asked of you. Check with your supervisor."); return; }
        setItem(found);
        const last = tickets.find((t) => t.competency.key === key);
        if (last?.status === "rejected") setSentBack(last.reason);
      })
      .catch((e) => setTrouble(plain(e)));
  }, [key, person]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!item || !front) return;
    setBusy(true);
    setError(null);
    try {
      const f = await api.upload("ticket", front);
      const b = back ? await api.upload("ticket", back) : null;
      await api.post("/v1/tickets", {
        competency: item.key, number: number.trim(), expires_on: item.card_expires ? expiresOn : null,
        front: f.id, back: b?.id ?? null,
      });
      setDone(true);
    } catch (err) {
      // one is waiting already (sent from another tab, or a tap that didn't seem to take): it's sent
      if (err instanceof ApiError && err.code === "already_waiting") setDone(true);
      else setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  if (done && item) {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Sent">
          <b>Sent</b>
          <span>Your {item.name} waits for a manager's check. It shows as done once they approve it.</span>
        </section>
        <Link to="/" className="big primary as-button">Back to My training</Link>
      </main>
    );
  }

  const ready = front && number.trim() && (!item?.card_expires || expiresOn);
  return (
    <main className="screen">
      <Back />
      {trouble && <div className="msg r" role="alert">{trouble}</div>}
      {!item && !trouble && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {item && (
        <>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{item.name}</h1>
          {sentBack && <div className="msg r">Your last one was sent back: {sentBack}</div>}
          <form onSubmit={send} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <PhotoPicker label="Photo of the front" hint="Tap to take it, or choose a PDF" file={front} onFile={setFront} />
            <PhotoPicker label="Photo of the back" hint="If there's anything on the back" file={back} onFile={setBack} />
            <label className="label">Number on the card
              <input className="input" autoComplete="off" autoCapitalize="characters" value={number}
                     onChange={(e) => setNumber(e.target.value)} maxLength={64} required />
            </label>
            {item.card_expires && (
              <label className="label">Good until (the date on the card)
                <input className="input" type="date" value={expiresOn} onChange={(e) => setExpiresOn(e.target.value)} required />
              </label>
            )}
            {error && <div className="msg r" role="alert">{error}</div>}
            <button type="submit" className="big primary" disabled={busy || !ready}>Send for checking</button>
          </form>
        </>
      )}
    </main>
  );
}
