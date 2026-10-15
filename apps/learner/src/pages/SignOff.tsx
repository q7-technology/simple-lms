import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Practical, SignsOff } from "../api/types";
import { useSession } from "../auth/Session";
import { toBlob } from "../lib/picture";
import { useDing } from "../lib/sound";
import { whenLine } from "../lib/training";
import { PhotoPicker, SignaturePad } from "../pictures";
import { Back, Logo, plain } from "../ui";

/** More people than this, and the list offers a search. */
const FIND_PAST = 6;

/** Who you may sign off (your team, or anyone for a manager), each with the
 * practicals they are asked for. */
export function SignOffPeople() {
  const [people, setPeople] = useState<SignsOff[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [find, setFind] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      setPeople(await api.get<SignsOff[]>("/v1/signoffs/people"));
    } catch (e) {
      setError(plain(e));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const wanted = find.trim().toLowerCase();
  const shown = people?.filter((p) => !wanted || p.name.toLowerCase().includes(wanted) || p.code.toLowerCase().includes(wanted));
  return (
    <main className="screen">
      <Back />
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>Sign someone off</h1>
      <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>Choose the person and the practical, then watch them do it.</p>
      {error && (
        <>
          <div className="msg r" role="alert">{error}</div>
          <button type="button" className="big primary" onClick={() => void load()}>Try again</button>
        </>
      )}
      {!people && !error && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {people && people.length === 0 && <div className="item"><b>Nobody to sign off</b><span>Nobody is on your team yet.</span></div>}
      {people && people.length > FIND_PAST && (
        <input className="input" aria-label="Find a person" placeholder="Name or code" value={find} onChange={(e) => setFind(e.target.value)} />
      )}
      {shown?.map((p) => (
        <section key={p.code} className="item" aria-label={p.name}>
          <b>{p.name}</b><span>{p.code}</span>
          {p.practicals.length === 0 && <span>Not asked for any practical.</span>}
          {p.practicals.map((c) => (
            <Link key={c.key} className="act" to={`/signoff/${encodeURIComponent(p.code)}/${encodeURIComponent(c.key)}`}
                  aria-label={`Sign off ${p.name}: ${c.name}`}>
              {c.name} · {whenLine({ ...c, kind: "practical", granted_on: null, card_expires: false, waiting: false })}
            </Link>
          ))}
        </section>
      ))}
    </main>
  );
}

type Step = "watch" | "confirm" | "done";

/** The sign-off itself, on the supervisor's phone. They watch, tick each
 * item, add a note or a photo if they like, and sign; then they hand the
 * phone over, and the learner checks what was ticked, signs, and types
 * their PIN to say it was them. The learner never signs in here: their PIN
 * goes with the sign-off and is never kept. */
export function SignOff() {
  const { code = "", key = "" } = useParams();
  const { person: signer } = useSession();
  const [learner, setLearner] = useState<SignsOff | null>(null);
  const [practical, setPractical] = useState<Practical | null>(null);
  const [trouble, setTrouble] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("watch");
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [signed, setSigned] = useState(false);
  // the photo and the signer's signature, once sent: the learner's turn next
  const [sent, setSent] = useState<{ photo: string | null; signature: string } | null>(null);
  const [theirsSigned, setTheirsSigned] = useState(false);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = useRef<HTMLCanvasElement>(null);
  const theirs = useRef<HTMLCanvasElement>(null);
  const { wake, ding } = useDing();

  const load = useCallback(async () => {
    setTrouble(null);
    try {
      const [people, checklist] = await Promise.all([
        api.get<SignsOff[]>("/v1/signoffs/people"),
        api.get<Practical>(`/v1/practicals/${encodeURIComponent(key)}`),
      ]);
      const p = people.find((x) => x.code === code);
      if (!p) { setTrouble("You can't sign this person off: they aren't on your team."); return; }
      setLearner(p);
      setPractical(checklist);
    } catch (e) {
      setTrouble(e instanceof ApiError && e.status === 404
        ? "There's no checklist for this practical yet. Ask your manager." : plain(e));
    }
  }, [code, key]);
  useEffect(() => { void load(); }, [load]);

  const items = useMemo(() => practical?.version.items ?? [], [practical]);
  const all = items.length > 0 && items.every((i) => ticked.has(i.id));

  function tick(id: number, on: boolean) {
    setTicked((t) => { const next = new Set(t); if (on) next.add(id); else next.delete(id); return next; });
  }

  /** Back to the signer, to tick and sign again. */
  function startAgain(why: string | null) {
    setPin("");
    setSent(null);
    setSigned(false);
    setTheirsSigned(false);
    setError(why);
    setStep("watch");
  }

  async function handOver(e: FormEvent) {
    e.preventDefault();
    if (!mine.current) return;
    setBusy(true);
    setError(null);
    try {
      const signature = await api.upload("signature", await toBlob(mine.current, "image/png"));
      const picture = photo ? await api.upload("signoff-photo", photo) : null;
      setSent({ photo: picture?.id ?? null, signature: signature.id });
      setStep("confirm");
    } catch (err) {
      setError(plain(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!theirs.current || !sent || !practical || !learner) return;
    // a phone only plays the Ding! that a tap started
    wake();
    setBusy(true);
    setError(null);
    // typed once, sent once, never kept
    const typed = pin;
    setPin("");
    try {
      const signature = await api.upload("signature", await toBlob(theirs.current, "image/png"));
      await api.post(`/v1/people/${encodeURIComponent(learner.code)}/signoffs`, {
        competency: practical.key, version: practical.version.version, ticked: items.map((i) => i.id),
        note: note.trim() || null, photo: sent.photo, supervisor_signature: sent.signature,
        learner_signature: signature.id, learner_pin: typed,
      });
      ding();
      setStep("done");
    } catch (err) {
      if (err instanceof ApiError && err.code === "new_version") {
        setTicked(new Set());
        startAgain("The checklist has changed: tick it again, then sign.");
        await load();
      } else {
        setError(plain(err));
      }
    } finally {
      setBusy(false);
    }
  }

  if (trouble) {
    return <main className="screen"><Back /><div className="msg r" role="alert">{trouble}</div></main>;
  }
  if (!learner || !practical) {
    return <main className="screen"><Back /><div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div></main>;
  }

  if (step === "done") {
    return (
      <main className="screen">
        <Back />
        <section className="ding" role="status" aria-label="Signed off">
          <b>Ding!</b>
          <span>{learner.name} is signed off for {practical.name}.</span>
        </section>
        <Link to="/signoff" className="big primary as-button">Sign someone else off</Link>
      </main>
    );
  }

  if (step === "confirm") {
    // the learner holds the phone now: nothing here leads to the signer's training
    return (
      <main className="screen">
        <div className="top"><Logo />Handed to {learner.name}</div>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{learner.name}, check and sign</h1>
        <p style={{ margin: 0 }}>{signer?.name} watched you do each of these for {practical.name}:</p>
        <ul className="policy" aria-label="What was ticked" style={{ margin: 0, paddingLeft: 32 }}>
          {items.map((i) => <li key={i.id}>{i.text}</li>)}
        </ul>
        {note.trim() && <p className="caption">Their note: “{note.trim()}”</p>}
        <form onSubmit={confirm} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <SignaturePad key="learner" canvas={theirs} onSigned={setTheirsSigned} />
          <div className="label">
            <label htmlFor="learner-pin">Your PIN</label>
            <span id="learner-pin-hint" className="small" style={{ fontWeight: 400, color: "var(--color-muted)" }}>
              It says it was you. It isn't kept on this phone.</span>
            <input id="learner-pin" className="input" type="password" inputMode="numeric" autoComplete="off" maxLength={8}
                   value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} aria-describedby="learner-pin-hint" />
          </div>
          {error && <div className="msg r" role="alert">{error}</div>}
          <button type="submit" className="big primary" disabled={busy || !theirsSigned || pin.length < 4}>Confirm</button>
          <button type="button" className="big ghost" onClick={() => startAgain(null)}>Give it back to {signer?.name}</button>
        </form>
      </main>
    );
  }

  return (
    <main className="screen">
      <Back />
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>{practical.name}</h1>
      <p style={{ margin: 0 }}>Watch {learner.name} do each of these, and tick it as they do.</p>
      <form onSubmit={handOver} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <fieldset className="question">
          <legend>Checklist, version {practical.version.version}</legend>
          {items.map((i) => (
            <label key={i.id} className="choice">
              <input type="checkbox" checked={ticked.has(i.id)} onChange={(e) => tick(i.id, e.target.checked)} />
              {i.text}
            </label>
          ))}
        </fieldset>
        <div className="small" aria-live="polite" style={{ color: "var(--color-muted)" }}>{items.filter((i) => ticked.has(i.id)).length} of {items.length} ticked</div>
        <div className="label">
          <label htmlFor="note">A note (optional)</label>
          <input id="note" className="input" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <PhotoPicker label="A photo (optional)" hint="Tap to take one" file={photo} onFile={setPhoto} removable pdf={false} />
        <p className="small" style={{ margin: 0, color: "var(--color-muted)" }}>
          Your signature says you watched {learner.name} do every item.</p>
        <SignaturePad key="signer" canvas={mine} onSigned={setSigned} />
        {error && <div className="msg r" role="alert">{error}</div>}
        <button type="submit" className="big primary" disabled={busy || !all || !signed}>Hand the phone to {learner.name}</button>
      </form>
    </main>
  );
}
