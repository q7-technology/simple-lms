import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { useGamePrefs } from "../lib/game";
import { groupTraining, nextStep, whenLine } from "../lib/training";
import { Logo, plain, Ring } from "../ui";

function SoundIcon({ on }: { on: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 5 }}>
      <path d="M11 5 6 9H3v6h3l5 4Z" />
      {on ? <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" /> : <path d="m16 9 5 6M21 9l-5 6" />}
    </svg>
  );
}

function Group({ title, tone, items, empty }: { title: string; tone: string; items: TrainingItem[]; empty: string }) {
  return (
    <section className="group" aria-label={title}>
      <h2>{title}<span className="sr-only">, </span><span className={`count ${tone}`}>{items.length}</span></h2>
      {items.length === 0 && <div className="small" style={{ color: "var(--color-muted)" }}>{empty}</div>}
      {items.map((i) => {
        const step = nextStep(i);
        return (
          <div key={i.key} className="item"><b>{i.name}</b><span>{whenLine(i)}</span>
            {step && "to" in step && <Link className="act" to={step.to} aria-label={`${step.label}: ${i.name}`}>{step.label}</Link>}
            {step && "waiting" in step && <span className="waiting">{step.waiting}</span>}
          </div>
        );
      })}
    </section>
  );
}

/** What is overdue, what is due soon and what is done; a policy to sign or a
 * ticket to send in opens from its item. */
export function MyTraining() {
  const { person, signOut } = useSession();
  const [prefs, setPrefs] = useGamePrefs();
  const [training, setTraining] = useState<Training | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setTraining(await api.get<Training>(`/v1/people/${encodeURIComponent(person!.code)}/training`));
    } catch (e) {
      setError(plain(e));
    }
  }, [person]);

  useEffect(() => { void load(); }, [load]);

  const g = training ? groupTraining(training.items) : null;
  return (
    <main className="screen">
      <div className="top"><Logo />{person?.name}
        {/* the one game touch with a switch: the ding out loud, on this device */}
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer" }} aria-pressed={prefs.sound}
                onClick={() => setPrefs({ sound: !prefs.sound })}><SoundIcon on={prefs.sound} />Sound</button>
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer", marginLeft: 0 }} onClick={signOut}>Sign out</button>
      </div>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800 }}>My training</h1>
      {error && (
        <>
          <div className="msg r" role="alert">{error}</div>
          <button type="button" className="big primary" onClick={() => void load()}>Try again</button>
        </>
      )}
      {!g && !error && <div aria-live="polite" style={{ color: "var(--color-muted)" }}>Loading…</div>}
      {g && training!.items.length === 0 && (
        <div className="item"><b>Nothing to do</b><span>Nothing is asked of you yet. Check with your supervisor.</span></div>
      )}
      {g && training!.items.length > 0 && (
        <>
          <Ring done={g.done.length} of={training!.items.length} />
          <Group title="Overdue" tone="t-red" items={g.overdue} empty="Nothing overdue." />
          <Group title="Due soon" tone="t-amber" items={g.dueSoon} empty="Nothing due in the next 30 days." />
          <Group title="Done" tone="t-green" items={g.done} empty="Nothing done yet." />
        </>
      )}
    </main>
  );
}
