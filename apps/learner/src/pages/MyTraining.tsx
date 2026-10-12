import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Training, TrainingItem } from "../api/types";
import { useSession } from "../auth/Session";
import { groupTraining, whenLine } from "../lib/training";
import { Logo } from "../ui";

function Group({ title, tone, items, empty }: { title: string; tone: string; items: TrainingItem[]; empty: string }) {
  return (
    <section className="group" aria-label={title}>
      <h2>{title}<span className="sr-only">, </span><span className={`count ${tone}`}>{items.length}</span></h2>
      {items.length === 0 && <div className="small" style={{ color: "var(--color-muted)" }}>{empty}</div>}
      {items.map((i) => (
        <div key={i.key} className="item"><b>{i.name}</b><span>{whenLine(i)}</span></div>
      ))}
    </section>
  );
}

/** Read only in step 1: what is overdue, what is due soon and what is done. */
export function MyTraining() {
  const { person, signOut } = useSession();
  const [training, setTraining] = useState<Training | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setTraining(await api.get<Training>(`/v1/people/${encodeURIComponent(person!.code)}/training`));
    } catch (e) {
      // plain words, never "Simple LMS answered 500"
      setError(e instanceof ApiError && e.status >= 500
        ? "Simple LMS isn't answering right now. Try again in a moment."
        : (e as Error).message);
    }
  }, [person]);

  useEffect(() => { void load(); }, [load]);

  const g = training ? groupTraining(training.items) : null;
  return (
    <main className="screen">
      <div className="top"><Logo />{person?.name}
        <button type="button" className="chip" style={{ border: 0, cursor: "pointer" }} onClick={signOut}>Sign out</button>
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
          <Group title="Overdue" tone="t-red" items={g.overdue} empty="Nothing overdue." />
          <Group title="Due soon" tone="t-amber" items={g.dueSoon} empty="Nothing due in the next 30 days." />
          <Group title="Done" tone="t-green" items={g.done} empty="Nothing done yet." />
        </>
      )}
    </main>
  );
}
